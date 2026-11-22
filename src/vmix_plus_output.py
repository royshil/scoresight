"""Discover vMix title fields and send each mapped value to every matching input.

Discovery and SetText use separate background workers. Each input/field has its
own sending key, so a failed title cannot prevent other titles from updating.
Input GUIDs survive reordering; discovery refreshes also find new titles and
backfill their fields with the last published readings, even if unchanged.
"""

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
from vmix_output import DEFAULT_VMIX_PORT, VMixAPI, VMixTCPPortError

REFRESH_SECONDS = 5.0


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
    def __init__(self, host, port, field_mapping):
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

    def set_connection(self, host, port):
        with self._lock:
            if (host, port) == (self.host, self.port):
                return
            self._epoch += 1
            self._fields = {}
            self._worker.clear()
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
        # The URL uses the queued host and input, never a new host combined with
        # an old input after a connection change.
        super()._send_text(key, value)

    def url_for(self, key, value):
        _, host, port, ref, field = key
        query = {
            "Function": "SetText",
            "Input": ref,
            "SelectedName": field,
            "Value": value,
        }
        return f"http://{host}:{port}/api/?{urlencode(query, quote_via=quote)}"
