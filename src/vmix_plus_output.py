"""Discover vMix title fields and send each mapped value to every matching input.

HTTP discovery and acknowledged TCP SetText use separate background workers. Each input/field has its
own sending key, so a failed title cannot prevent other titles from updating.
Input GUIDs survive reordering; discovery refreshes also find new titles and
backfill their fields with the last published readings, even if unchanged.
"""

import socket
import threading
import time
import xml.etree.ElementTree as ET
from urllib.parse import quote, urlencode

import requests

from output_worker import (
    HTTP_TIMEOUT,
    OutputError,
    OutputWorker,
    SendSkipped,
    check_http_response,
)
from vmix_output import DEFAULT_VMIX_PORT, VMIX_TCP_API_PORT, VMixAPI, VMixTCPPortError

REFRESH_SECONDS = 5.0


class VMixFunctionError(OutputError):
    """vMix rejected this FUNCTION; other fields may still succeed."""


class VMixTCPClient:
    """One persistent connection, used by the sender worker, interruptible by Stop.

    A command is acknowledged before the next is sent. Optional VERSION/TALLY/
    ACTS lines may arrive before a FUNCTION reply. Buffers and deadlines bound
    reads; a failed exchange discards the connection to avoid shifted replies.
    """

    TIMEOUT = 2.0
    MAX_LINE = 65536

    def __init__(self):
        self._lock = threading.Lock()
        self._generation = 0
        self._stream = None  # (target, socket, bytearray); only worker mutates buffer

    def generation(self):
        with self._lock:
            return self._generation

    @staticmethod
    def _close_socket(sock):
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        sock.close()

    def close(self):
        with self._lock:
            self._generation += 1
            stream, self._stream = self._stream, None
        if stream:
            self._close_socket(stream[1])

    def _connection(self, target, generation):
        with self._lock:
            if generation != self._generation:
                raise SendSkipped()
            if self._stream and self._stream[0] == target:
                return self._stream
            old, self._stream = self._stream, None
        if old:
            self._close_socket(old[1])
        _, host, port = target
        sock = socket.create_connection((host, int(port)), timeout=self.TIMEOUT)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        stream = (target, sock, bytearray())
        with self._lock:
            if generation != self._generation:
                self._close_socket(sock)
                raise SendSkipped()
            self._stream = stream
        return stream

    def _line(self, stream, deadline, generation):
        _, sock, buffer = stream
        while True:
            if generation != self.generation():
                raise SendSkipped()
            if b"\r\n" in buffer:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise socket.timeout("Timed out waiting for vMix TCP acknowledgement")
            # Short receive waits also make cancellation prompt on platforms
            # where closing a socket does not immediately wake a timed recv.
            sock.settimeout(min(remaining, 0.1))
            try:
                data = sock.recv(4096)
            except socket.timeout:
                continue
            if not data:
                raise ConnectionError(
                    "vMix TCP connection closed before acknowledgement"
                )
            buffer.extend(data)
            if len(buffer) > self.MAX_LINE:
                raise ConnectionError("vMix TCP reply exceeded the line limit")
        line, _, rest = buffer.partition(b"\r\n")
        buffer[:] = rest
        return line.decode("utf-8")

    def set_text(self, target, generation, ref, field, value):
        query = urlencode(
            {"Input": ref, "SelectedName": field, "Value": value}, quote_via=quote
        )
        try:
            stream = self._connection(target, generation)
            stream[1].settimeout(self.TIMEOUT)
            stream[1].sendall(f"FUNCTION SetText {query}\r\n".encode("utf-8"))
            deadline = time.monotonic() + self.TIMEOUT
            for _ in range(128):
                line = self._line(stream, deadline, generation)
                command, _, rest = line.partition(" ")
                status, _, detail = rest.partition(" ")
                if command == "FUNCTION":
                    if status == "OK":
                        return
                    if status == "ER":
                        raise VMixFunctionError(
                            f"vMix rejected {field!r} in input {ref!r}: {detail}"
                        )
                elif command in ("VERSION", "TALLY", "ACTS") and status == "OK":
                    continue
                raise ConnectionError(f"Unexpected vMix TCP reply: {line[:200]}")
            raise ConnectionError("Too many events before vMix TCP acknowledgement")
        except socket.timeout as error:
            cancelled = generation != self.generation()
            self.close()
            if cancelled:
                raise SendSkipped() from error
            raise requests.Timeout(str(error)) from error
        except (OSError, UnicodeError, ValueError) as error:
            cancelled = generation != self.generation()
            self.close()
            if cancelled:
                raise SendSkipped() from error
            raise requests.ConnectionError(str(error)) from error


def title_fields(xml: str) -> dict[str, tuple[str, ...]]:
    """Exact text-field name -> input GUIDs (input numbers only as a fallback)."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as error:
        raise OutputError("vMix API+ did not receive valid XML from /api/") from error
    if root.tag != "vmix" or root.find("inputs") is None:
        raise OutputError("vMix API+ expected a vMix XML document with inputs")
    fields: dict[str, list[str]] = {}
    for input_el in root.findall("./inputs/input"):
        ref = input_el.get("key") or input_el.get("number")
        if not ref:
            continue
        for text in input_el.findall("text"):
            name = text.get("name")
            if name and ref not in fields.setdefault(name, []):
                fields[name].append(ref)
    return {name: tuple(refs) for name, refs in fields.items()}


class VMixPlusAPI(VMixAPI):
    def __init__(self, host, port, field_mapping, *, tcp_port=VMIX_TCP_API_PORT):
        self._tcp = VMixTCPClient()
        self.tcp_port = str(tcp_port)
        self._lock = threading.RLock()
        self._epoch = 0
        self._closed = False
        self._fields: dict[str, tuple[str, ...]] = {}
        self._values: dict[str, str] = {}
        self._refresh_at: float | None = None
        super().__init__(
            host,
            port,
            "",
            dict(field_mapping),
            settings_key="vmix_plus_send_same",
            name="vMix API+",
        )
        self._discovery_session = requests.Session()
        self._discovery = OutputWorker(
            "vMix API+ discovery",
            self._discover,
            retry_on=(requests.ConnectionError, requests.Timeout),
        )

    def fields(self) -> dict[str, tuple[str, ...]]:
        with self._lock:
            return dict(self._fields)

    def discovery_status(self):
        return self._discovery.status()

    def refresh_fields(self):
        """Request discovery, also while stopped. Never waits for the network."""
        with self._lock:
            if self._closed:
                return
            self._refresh_at = time.monotonic()
            self._discovery.submit("fields", (self._epoch, self.host, self.port))

    def refresh(self, now=None):
        """Called by the status timer; periodic discovery runs only while on."""
        now = time.monotonic() if now is None else now
        with self._lock:
            if self.running and (
                self._refresh_at is None or now - self._refresh_at >= REFRESH_SECONDS
            ):
                self.refresh_fields()

    def set_connection(self, host, port, *, tcp_port=None):
        with self._lock:
            tcp_port = self.tcp_port if tcp_port is None else str(tcp_port)
            if (host, port, tcp_port) == (self.host, self.port, self.tcp_port):
                return
            self._epoch += 1
            self.tcp_port = tcp_port
            self._tcp.close()
            self._fields = {}
            self._worker.clear()
            self._worker.reset_status()
            self._discovery.clear()
            self._discovery.reset_status()
            super().set_connection(host, port, "")
            self._refresh_at = None
            if self.running:
                self.refresh_fields()

    def set_field_mapping(self, field_mapping):
        with self._lock:
            if dict(field_mapping) == self.field_mapping:
                return
            self.field_mapping = dict(field_mapping)
            self._values = {
                name: value
                for name, value in self._values.items()
                if name in self.field_mapping
            }
            self._worker.clear()
            self._worker.reset_status()
            self._queue_values()

    def start(self):
        with self._lock:
            if self._closed or self.running:
                return
            self._epoch += 1
            self._fields = {}
            self.running = True
            self.refresh_fields()

    def stop(self):
        with self._lock:
            self._epoch += 1
            self._tcp.close()
            self._fields = {}
            self._discovery.clear()
            self._discovery.reset_status()
            super().stop()

    def close(self):
        with self._lock:
            self._closed = True
        super().close()
        self._discovery.stop()

    def update_vmix(self, detection, resend_unchanged=()):
        # Remember good published values while off too, so Start and newly
        # discovered titles get an unchanged value without waiting for a change.
        with self._lock:
            for result in detection:
                if result.result_state.name not in ("Success", "SameNoChange"):
                    continue
                if result.name not in self.field_mapping:
                    continue
                self._values[result.name] = (
                    "" if result.result is None else str(result.result)
                )
                if (
                    result.result_state.name == "Success"
                    or self.update_same
                    or result.name in resend_unchanged
                ):
                    self._queue_values(names=(result.name,))

    def _queue_values(self, names=None, only_pairs=None):
        # Caller holds _lock; all queued keys and values are immutable snapshots.
        if not self.running:
            return
        for name in self._values if names is None else names:
            field = self.field_mapping.get(name)
            if not field or name not in self._values:
                continue
            for ref in self._fields.get(field, ()):
                if only_pairs is None or (ref, field) in only_pairs:
                    key = (self._epoch, self.host, self.port, ref, field)
                    self._worker.submit(key, self._values[name])

    def _discover(self, _, connection):
        epoch, host, port = connection
        try:
            response = self._discovery_session.get(
                f"http://{host}:{port}/api/", timeout=HTTP_TIMEOUT
            )
        except requests.ConnectionError as error:
            if "VERSION OK" in str(error):
                raise VMixTCPPortError(
                    f"{host}:{port} answered like the vMix TCP API ('VERSION OK'). "
                    f"Use the Web Controller port ({DEFAULT_VMIX_PORT} by default)."
                ) from error
            raise
        check_http_response(response, "vMix API+ field discovery")
        fields = title_fields(response.text)
        with self._lock:
            if self._closed or epoch != self._epoch:
                raise SendSkipped()
            previous = {
                (ref, field) for field, refs in self._fields.items() for ref in refs
            }
            current = {(ref, field) for field, refs in fields.items() for ref in refs}
            self._fields = fields
            self._worker.forget_keys(
                lambda key: key[0] != epoch or (key[3], key[4]) not in current
            )
            self._queue_values(only_pairs=current - previous)

    def _send_text(self, key, value):
        epoch, _, _, ref, field = key
        with self._lock:
            if (
                not self.running
                or epoch != self._epoch
                or ref not in self._fields.get(field, ())
                or field not in self.field_mapping.values()
            ):
                raise SendSkipped()
            tcp_generation = self._tcp.generation()
            tcp_target = (epoch, self.host, self.tcp_port)
        self._tcp.set_text(tcp_target, tcp_generation, ref, field, value)
