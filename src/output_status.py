"""The output destinations (text files, HTTP server, OBS, vMix, UNO, the
outbound HTTP API and the TCP / UDP output) and how each one is doing.

For every destination a DestinationStatus says whether it is on, its state, a
short line about what is happening ("Connected to localhost:4455", "Can't reach
192.168.1.40:8088 · retrying", "HTTP 401: vMix asks for a login"...), what to do
about a problem, and when it last sent something.

The functions here only read snapshots that are cheap to take and never wait
for the network: OutputWorker.status() (vMix, UNO, OBS, the outbound API, TCP),
TcpOutput.connection_status(), http_server_stats() and FileOutput.status(). MainWindow builds the statuses
about once a second on the GUI thread; destinations_view.py (the destinations
list) and status_bar.py (the outputs summary) show them.

Each state has its own glyph shape (● ◐ ▲ ■ ○) besides its colour, so the
state never depends on colour alone. Secrets (the UNO URL's token, a key in the
API URL) never appear in what is shown.
"""

import re
import socket
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

import requests
import websocket
from obsws_python.error import OBSSDKError, OBSSDKRequestError, OBSSDKTimeoutError
from PySide6.QtCore import QCoreApplication

from file_output import FileOutputStatus
from http_server import HttpServerStats
from obs_websocket import OBSConnectionLost
from output_worker import ErrorInfo, OutputError, RetryLater, WorkerStatus
from tcp_output import (
    CASPARCG,
    UDP,
    WEBSOCKET,
    ConnectionStatus,
    ListenError,
    TcpConfig,
    WebSocketRefused,
)
from vmix_output import DEFAULT_VMIX_PORT, VMixTCPPortError

# the destinations, in the order of the list and of the output pages
FILES = "files"
HTTP = "http"
OBS = "obs"
VMIX = "vmix"
UNO = "uno"
API = "api"
TCP = "tcp"
TEAM_PERFORMANCE = "team_performance"
DESTINATIONS = (FILES, HTTP, OBS, VMIX, UNO, API, TCP, TEAM_PERFORMANCE)

# states
OFF = "off"  # turned off (or not connected)
SENDING = "sending"  # on, nothing delivered yet (connecting, waiting for values)
OK = "ok"  # on and delivering
WARNING = "warning"  # on, but partly failing or not fully set up
RETRYING = "retrying"  # can't reach the target, retrying by itself
ERROR = "error"  # needs action
STATES = (OFF, SENDING, OK, WARNING, RETRYING, ERROR)
PROBLEM_STATES = (WARNING, RETRYING, ERROR)

# the glyph of each state, as text (tooltips, the status bar's accessible
# names) and as a shape drawn by theme.draw_state_shape()
STATE_GLYPHS = {
    OK: "●",
    SENDING: "◐",
    WARNING: "▲",
    RETRYING: "▲",
    ERROR: "■",
    OFF: "○",
}
STATE_SHAPES = {
    OK: "disc",
    SENDING: "half",
    WARNING: "triangle",
    RETRYING: "triangle",
    ERROR: "square",
    OFF: "ring",
}
# the theme colour of each state (theme.color); None: the muted text colour
STATE_COLORS = {
    OK: "new",
    SENDING: None,
    WARNING: "rejected",
    RETRYING: "rejected",
    ERROR: "empty",
    OFF: None,
}

# what the last activity of a destination is
ACTIVITY_SENT = "sent"
ACTIVITY_WRITTEN = "written"
ACTIVITY_REQUEST = "request"

# placeholder URL of the UNO page (not a real URL)
UNO_PLACEHOLDER_MARK = "..."


@dataclass(frozen=True)
class DestinationStatus:
    key: str
    state: str
    detail: str  # one short line
    enabled: bool = False  # on (the switch)
    switchable: bool = True  # has an on/off switch (the HTTP server hasn't)
    hint: str = ""  # what to do about a problem, or more about the state
    last_activity_at: float | None = None  # time.monotonic()
    activity: str = ACTIVITY_SENT
    technical: str = ""  # the latest error, as logged (without secrets)

    @property
    def has_problem(self) -> bool:
        return self.state in PROBLEM_STATES


@dataclass(frozen=True)
class Problem:
    state: str
    detail: str
    hint: str = ""


# --- names and texts ----------------------------------------------------------


def destination_name(key: str) -> str:
    """The destination's name in the list ("Text files", "vMix"...)."""
    if key == FILES:
        return QCoreApplication.translate("OutputStatus", "Text files")
    if key == HTTP:
        return QCoreApplication.translate("OutputStatus", "HTTP server")
    if key == TEAM_PERFORMANCE:
        return "Team Performance"
    if key == API:
        return QCoreApplication.translate("OutputStatus", "HTTP API")
    return {OBS: "OBS", VMIX: "vMix", UNO: "UNO", TCP: "TCP / UDP"}.get(key, key)


def short_name(key: str) -> str:
    """The destination's name in the status bar ("Files", "HTTP"...)."""
    if key == FILES:
        return QCoreApplication.translate("OutputStatus", "Files")
    return {
        HTTP: "HTTP",
        OBS: "OBS",
        VMIX: "vMix",
        UNO: "UNO",
        API: "API",
        TCP: "TCP",
        TEAM_PERFORMANCE: "TP",
    }.get(key, key)


def destination_description(key: str) -> str:
    """What the destination does (the output tabs' tooltips before 0.2.0)."""
    texts = {
        TEAM_PERFORMANCE: QCoreApplication.translate(
            "OutputStatus", "Serve scoreboard and shot-clock times to Team Performance"
        ),
        FILES: QCoreApplication.translate(
            "MainWindow", "Write the readings to .txt, .csv and .xml files"
        ),
        HTTP: QCoreApplication.translate(
            "MainWindow",
            "The built-in HTTP server: a scoreboard page, JSON, XML and CSV",
        ),
        OBS: QCoreApplication.translate(
            "MainWindow", "Update text sources in OBS Studio"
        ),
        VMIX: QCoreApplication.translate("MainWindow", "Update a title in vMix"),
        UNO: QCoreApplication.translate(
            "MainWindow", "Drive an overlays.uno control app"
        ),
        API: QCoreApplication.translate(
            "MainWindow", "Send the readings to a URL (outbound HTTP API)"
        ),
        TCP: QCoreApplication.translate(
            "OutputStatus",
            "Send the readings over TCP or UDP: CasparCG, Chyron PRIME, Live Score, "
            "MagicSoft CG, Vizrt and other graphics systems",
        ),
    }
    return texts.get(key, "")


def state_word(state: str) -> str:
    """The state in a word or two, for tooltips and screen readers."""
    if state == OK:
        return QCoreApplication.translate("OutputStatus", "working")
    if state == SENDING:
        return QCoreApplication.translate("OutputStatus", "waiting")
    if state == WARNING:
        return QCoreApplication.translate("OutputStatus", "needs attention")
    if state == RETRYING:
        return QCoreApplication.translate("OutputStatus", "retrying")
    if state == ERROR:
        return QCoreApplication.translate("OutputStatus", "not working")
    return QCoreApplication.translate("OutputStatus", "off")


def age_text(seconds: float) -> str:
    """How long ago: "just now", "3 s ago", "2 min ago", "1 h ago"."""
    seconds = max(0, int(seconds))
    if seconds < 1:
        return QCoreApplication.translate("OutputStatus", "just now")
    if seconds < 60:
        return QCoreApplication.translate("OutputStatus", "{seconds} s ago").format(
            seconds=seconds
        )
    if seconds < 3600:
        return QCoreApplication.translate("OutputStatus", "{minutes} min ago").format(
            minutes=seconds // 60
        )
    return QCoreApplication.translate("OutputStatus", "{hours} h ago").format(
        hours=seconds // 3600
    )


def wait_text(seconds: float) -> str:
    """A wait: "a few seconds", "40 s", "3 min", "2 h"."""
    seconds = max(0, int(round(seconds)))
    if seconds < 5:
        return QCoreApplication.translate("OutputStatus", "a few seconds")
    if seconds < 60:
        return QCoreApplication.translate("OutputStatus", "{seconds} s").format(
            seconds=seconds
        )
    if seconds < 3600:
        return QCoreApplication.translate("OutputStatus", "{minutes} min").format(
            minutes=-(-seconds // 60)
        )
    return QCoreApplication.translate("OutputStatus", "{hours} h").format(
        hours=-(-seconds // 3600)
    )


def activity_text(status: DestinationStatus, now: float) -> str:
    """E.g. "Last sent 3 s ago" (or written, request), or "" before any."""
    if status.last_activity_at is None:
        return ""
    age = age_text(now - status.last_activity_at)
    if status.activity == ACTIVITY_WRITTEN:
        return QCoreApplication.translate("OutputStatus", "Last written {age}").format(
            age=age
        )
    if status.activity == ACTIVITY_REQUEST:
        return QCoreApplication.translate("OutputStatus", "Last request {age}").format(
            age=age
        )
    return QCoreApplication.translate("OutputStatus", "Last sent {age}").format(age=age)


def status_tooltip(status: DestinationStatus, now: float) -> str:
    """The full status, for the tooltips of the list and the status bar."""
    lines = [
        f"{destination_name(status.key)}: {STATE_GLYPHS[status.state]} "
        f"{state_word(status.state)}",
        status.detail,
    ]
    if status.hint:
        lines.append(status.hint)
    activity = activity_text(status, now)
    if activity:
        lines.append(activity)
    if status.technical and status.has_problem:
        lines.append(
            QCoreApplication.translate("OutputStatus", "Details: {error}").format(
                error=status.technical
            )
        )
    return "\n".join(line for line in lines if line)


def accessible_text(status: DestinationStatus) -> str:
    """The destination, on or off, the state and the detail (no age: screen
    readers don't need it updated every second)."""
    parts = [destination_name(status.key)]
    if status.switchable:
        parts.append(
            QCoreApplication.translate("OutputStatus", "on")
            if status.enabled
            else QCoreApplication.translate("OutputStatus", "off")
        )
    if status.state != OFF:
        parts.append(state_word(status.state))
    parts.append(status.detail)
    return ", ".join(part for part in parts if part)


def elide_middle(text: str, limit: int = 40) -> str:
    if len(text) <= limit:
        return text
    keep = (limit - 1) // 2
    return f"{text[:keep]}…{text[-keep:]}"


# --- secrets -----------------------------------------------------------------


# a path segment this long may be a key (webhook URLs carry one in their path)
_SECRET_SEGMENT_LENGTH = 16


def url_secrets(url: str | None, path_is_secret: bool = False) -> list[str]:
    """The parts of a URL that must not be shown: a password, the query and
    its values (they may hold a key), long path segments (webhook keys) and,
    for the UNO URL, the whole path (it holds the token)."""
    if not url:
        return []
    try:
        parts = urlsplit(url)
        password = parts.password
    except ValueError:
        return [url]
    secrets = []
    if password:
        secrets.append(password)
    if parts.query:
        secrets.append(parts.query)
        # the values alone (a message may show them encoded differently)
        for pair in parts.query.split("&"):
            _, _, value = pair.partition("=")
            if len(value) >= 4:
                secrets.append(value)
    min_length = 12 if path_is_secret else _SECRET_SEGMENT_LENGTH
    if path_is_secret and parts.path not in ("", "/"):
        secrets.append(parts.path)
    # a token in the path alone, e.g. as the URL-encoded part of another message
    secrets.extend(
        segment for segment in parts.path.split("/") if len(segment) >= min_length
    )
    return secrets


def redact(text: str, secrets: Iterable[str]) -> str:
    """text with every secret replaced by "…"."""
    for secret in sorted((s for s in secrets if s), key=len, reverse=True):
        text = text.replace(secret, "…")
    return text


def url_target(url: str | None) -> str | None:
    """The "host:port" (or "host") of a URL, without a user name or password."""
    if not url:
        return None
    try:
        parts = urlsplit(url)
        host, port = parts.hostname, parts.port
    except ValueError:
        return None
    if not host:
        return None
    if ":" in host:
        host = f"[{host}]"
    return f"{host}:{port}" if port else host


# --- errors -------------------------------------------------------------------

_DNS_MARKERS = (
    "failed to resolve",
    "getaddrinfo failed",
    "name or service not known",
    "nodename nor servname",
    "no address associated",
    "temporary failure in name resolution",
    "name resolution",
)
_REFUSED_MARKERS = (
    "refused",
    "10061",
    "errno 111",
    "econnrefused",
    "errno 61]",
)


def _is_a(error: ErrorInfo, *types) -> bool:
    return isinstance(error.type, type) and issubclass(error.type, types)


def _is_timeout(error: ErrorInfo) -> bool:
    return _is_a(
        error,
        requests.Timeout,
        TimeoutError,
        socket.timeout,
        OBSSDKTimeoutError,
        websocket.WebSocketTimeoutException,
    ) or ("timed out" in error.message.lower() and not _is_refused(error))


def _is_refused(error: ErrorInfo) -> bool:
    return _is_a(error, ConnectionRefusedError) or any(
        marker in error.message.lower() for marker in _REFUSED_MARKERS
    )


def _is_dns(error: ErrorInfo) -> bool:
    return _is_a(error, socket.gaierror) or any(
        marker in error.message.lower() for marker in _DNS_MARKERS
    )


def _is_connection_problem(error: ErrorInfo) -> bool:
    return error.unreachable or _is_a(
        error,
        OSError,
        websocket.WebSocketException,
        OBSConnectionLost,
        requests.ConnectionError,
    )


def _server_message(error: ErrorInfo) -> str:
    """The text an HTTP endpoint answered with ("... returned HTTP 500: text")."""
    _, separator, body = error.message.partition(f"HTTP {error.code}: ")
    return body.strip() if separator else ""


def _host_and_port(target: str | None) -> tuple[str, str]:
    if not target:
        return "", ""
    host, separator, port = target.rpartition(":")
    if not separator or "]" in port:
        return target, ""
    return host, port


def _retrying(detail: str, unreachable: bool) -> str:
    if not unreachable:
        return detail
    return QCoreApplication.translate("OutputStatus", "{problem} · retrying").format(
        problem=detail
    )


def describe_error(
    key: str, error: ErrorInfo, target: str | None, secrets: Iterable[str] = ()
) -> Problem:
    """A short, plain description of a failure of destination key, and what to
    do about it. target is "host:port" (or the host) the destination sends to."""
    target = target or "?"
    host, port = _host_and_port(target)
    message = error.message.lower()
    unreachable = error.unreachable
    state = RETRYING if unreachable else ERROR

    # vMix answered like its TCP API ("VERSION OK ..." instead of HTTP): the
    # port is wrong (issue #55)
    if key == VMIX and (_is_a(error, VMixTCPPortError) or "version ok" in message):
        return Problem(
            ERROR,
            QCoreApplication.translate(
                "OutputStatus", "Port {port} is vMix's TCP API: use {web_port}"
            ).format(port=port or "?", web_port=DEFAULT_VMIX_PORT),
            QCoreApplication.translate(
                "OutputStatus",
                "ScoreSight uses the vMix Web API. Set the port to the Web "
                "Controller port (vMix Settings › Web Controller, {web_port} by "
                "default).",
            ).format(web_port=DEFAULT_VMIX_PORT),
        )

    # OBS refused the connection (at connect time)
    if (
        key == OBS
        and _is_a(error, OBSSDKError)
        and not _is_a(error, OBSSDKTimeoutError)
    ):
        if "no password" in message:
            return Problem(
                ERROR,
                QCoreApplication.translate("OutputStatus", "OBS needs a password"),
                QCoreApplication.translate(
                    "OutputStatus",
                    "Enter the password of OBS's WebSocket server (in OBS: Tools › "
                    "WebSocket Server Settings › Show Connect Info).",
                ),
            )
        if "identify" in message or "authentic" in message:
            return Problem(
                ERROR,
                QCoreApplication.translate(
                    "OutputStatus", "OBS refused the connection: check the password"
                ),
                QCoreApplication.translate(
                    "OutputStatus",
                    "The password doesn't match the one of OBS's WebSocket server "
                    "(in OBS: Tools › WebSocket Server Settings › Show Connect Info).",
                ),
            )

    # an OBS request failed: usually a text source that doesn't exist
    if key == OBS and _is_a(error, OBSSDKRequestError):
        if error.code == 600:
            match = re.search(r"`([^`]+)`", error.message) or re.search(
                r"name of [\"'“]?([^\"'”.]+)", error.message
            )
            if match:
                detail = QCoreApplication.translate(
                    "OutputStatus", "OBS has no text source “{name}”"
                ).format(name=match.group(1))
            else:
                detail = QCoreApplication.translate(
                    "OutputStatus", "OBS has no text source with a field's name"
                )
            return Problem(
                ERROR,
                detail,
                QCoreApplication.translate(
                    "OutputStatus",
                    "Create a text source with this name in OBS (names are "
                    "case-sensitive), or use Create OBS Scene.",
                ),
            )
        return Problem(
            ERROR,
            QCoreApplication.translate(
                "OutputStatus", "OBS refused an update (code {code})"
            ).format(code=error.code if error.code is not None else "?"),
            redact(error.message, secrets),
        )

    # HTTP error statuses (the endpoint answered)
    if key in (VMIX, UNO, API) and error.code is not None and _is_a(error, OutputError):
        return _describe_http_status(key, error, secrets)
    # a WebSocket server refused the handshake (the TCP / UDP output)
    if key == TCP and error.code is not None and _is_a(error, WebSocketRefused):
        return _describe_http_status(key, error, secrets)

    # retrying doesn't help with these
    if _is_a(error, requests.exceptions.SSLError) or "certificate verify" in message:
        return Problem(
            ERROR,
            QCoreApplication.translate(
                "OutputStatus", "No secure connection to {target}"
            ).format(target=target),
            QCoreApplication.translate(
                "OutputStatus",
                "The HTTPS connection failed (for example, the server's "
                "certificate isn't trusted). Check the URL; on your own network, "
                "http:// may be what the receiver expects.",
            ),
        )
    if _is_a(
        error,
        requests.exceptions.InvalidURL,
        requests.exceptions.MissingSchema,
        requests.exceptions.InvalidSchema,
    ):
        return Problem(
            ERROR,
            QCoreApplication.translate("OutputStatus", "The URL isn't valid"),
            QCoreApplication.translate(
                "OutputStatus",
                "The URL needs a scheme and a host, for example "
                "http://192.168.1.10:8091/scores.",
            ),
        )

    if _is_dns(error):
        return Problem(
            state,
            _retrying(
                QCoreApplication.translate("OutputStatus", "Can't find {host}").format(
                    host=host or target
                ),
                unreachable,
            ),
            QCoreApplication.translate(
                "OutputStatus",
                "The address {host} isn't known on this network: check it, or use "
                "the computer's IP address.",
            ).format(host=host or target),
        )

    if _is_timeout(error):
        if key in (VMIX, OBS):
            hint = " ".join(
                (
                    QCoreApplication.translate(
                        "OutputStatus", "Nothing answered within a few seconds."
                    ),
                    _unreachable_hint(key, target, port),
                )
            )
        elif port:
            hint = QCoreApplication.translate(
                "OutputStatus",
                "Nothing answered within a few seconds: the computer may be off, "
                "the address wrong, or a firewall may block port {port}.",
            ).format(port=port)
        else:
            hint = QCoreApplication.translate(
                "OutputStatus",
                "Nothing answered within a few seconds: check this computer's "
                "network connection.",
            )
        return Problem(
            state,
            _retrying(
                QCoreApplication.translate(
                    "OutputStatus", "No answer from {target}"
                ).format(target=target),
                unreachable,
            ),
            hint,
        )

    if _is_refused(error) or (_is_connection_problem(error) and key != OBS):
        return Problem(
            state,
            _retrying(
                QCoreApplication.translate(
                    "OutputStatus", "Can't reach {target}"
                ).format(target=target),
                unreachable,
            ),
            _unreachable_hint(key, target, port),
        )

    if key == OBS and _is_connection_problem(error):
        return Problem(
            state,
            _retrying(
                QCoreApplication.translate(
                    "OutputStatus", "Lost the connection to OBS at {target}"
                ).format(target=target),
                unreachable,
            ),
            QCoreApplication.translate(
                "OutputStatus",
                "ScoreSight reconnects by itself as soon as OBS is reachable "
                "again. Check that OBS is running.",
            ),
        )

    # anything else: the error itself, shortened
    text = redact(str(error), secrets)
    return Problem(state, _retrying(elide_middle(text, 70), unreachable), "")


def _unreachable_hint(key: str, target: str, port: str) -> str:
    if key == VMIX:
        return QCoreApplication.translate(
            "OutputStatus",
            "Check that vMix is running, that its Web Controller is enabled "
            "(vMix Settings › Web Controller) on port {port}, and that the "
            "firewall of the vMix computer allows it.",
        ).format(port=port or DEFAULT_VMIX_PORT)
    if key == OBS:
        return QCoreApplication.translate(
            "OutputStatus",
            "Check that OBS is running and that its WebSocket server is enabled "
            "(in OBS: Tools › WebSocket Server Settings) on port {port}.",
        ).format(port=port or "4455")
    if key == UNO:
        return QCoreApplication.translate(
            "OutputStatus", "Check this computer's internet connection."
        )
    if key == TCP:
        return QCoreApplication.translate(
            "OutputStatus",
            "Check that the receiving program is running and accepts connections "
            "on port {port}, and that the firewall of its computer allows it.",
        ).format(port=port or "?")
    return QCoreApplication.translate(
        "OutputStatus",
        "Nothing answers at {target}: check the URL and that the receiving "
        "program is running.",
    ).format(target=target)


def _describe_http_status(key: str, error: ErrorInfo, secrets) -> Problem:
    code = error.code
    server = redact(_server_message(error), secrets)
    if code in (401, 403):
        if key == VMIX:
            return Problem(
                ERROR,
                QCoreApplication.translate(
                    "OutputStatus", "HTTP {code}: vMix asks for a login"
                ).format(code=code),
                QCoreApplication.translate(
                    "OutputStatus",
                    "In vMix Settings › Web Controller, tick “Allow access to "
                    "following pages without login: API”. ScoreSight doesn't send "
                    "a vMix login.",
                ),
            )
        if key == UNO:
            return Problem(
                ERROR,
                QCoreApplication.translate(
                    "OutputStatus", "HTTP {code}: check the UNO URL"
                ).format(code=code),
                QCoreApplication.translate(
                    "OutputStatus",
                    "overlays.uno refused the URL: it is wrong or no longer valid. "
                    "Copy the API URL of your control app again.",
                ),
            )
        return Problem(
            ERROR,
            QCoreApplication.translate(
                "OutputStatus", "HTTP {code}: access denied"
            ).format(code=code),
            QCoreApplication.translate(
                "OutputStatus",
                "The endpoint refused the request. If it needs a login, put it in "
                "the URL (http://user:password@host/...); a key or token goes in "
                "the URL or in Headers.",
            ),
        )
    if code == 404:
        if key == VMIX:
            return Problem(
                ERROR,
                QCoreApplication.translate(
                    "OutputStatus", "HTTP 404: this isn't the vMix Web API"
                ),
                QCoreApplication.translate(
                    "OutputStatus",
                    "Check the host and the port: vMix's Web Controller port "
                    "({port} by default).",
                ).format(port=DEFAULT_VMIX_PORT),
            )
        if key == UNO:
            return Problem(
                ERROR,
                QCoreApplication.translate(
                    "OutputStatus", "HTTP {code}: check the UNO URL"
                ).format(code=code),
                QCoreApplication.translate(
                    "OutputStatus",
                    "overlays.uno refused the URL: it is wrong or no longer valid. "
                    "Copy the API URL of your control app again.",
                ),
            )
        return Problem(
            ERROR,
            QCoreApplication.translate("OutputStatus", "HTTP 404: check the URL"),
            QCoreApplication.translate(
                "OutputStatus",
                "The endpoint has nothing at this address: check the path.",
            ),
        )
    if code == 429:
        if key == UNO:
            detail = QCoreApplication.translate(
                "OutputStatus", "HTTP 429: overlays.uno's call limit reached"
            )
            hint = QCoreApplication.translate(
                "OutputStatus",
                "overlays.uno limits the calls of your plan (the Free plan: about "
                "10,000 a day). ScoreSight keeps the latest value of each field "
                "and sends it when the limit resets. To use fewer calls, keep "
                "“Also resend unchanged values” off and clear the command of "
                "fields the overlay doesn't use.",
            )
        else:
            detail = QCoreApplication.translate(
                "OutputStatus", "HTTP 429: too many requests"
            )
            hint = QCoreApplication.translate(
                "OutputStatus",
                "The endpoint limits the requests. ScoreSight keeps the latest "
                "readings and sends them when it accepts requests again. To send "
                "fewer, turn on “Only changes”, set a “Rate”, or lower "
                "Detections / s.",
            )
        return Problem(WARNING, _retrying(detail, error.unreachable), hint)
    if code == 400 and key == UNO:
        return Problem(
            ERROR,
            QCoreApplication.translate(
                "OutputStatus", "HTTP 400: overlays.uno doesn't know a command"
            ),
            QCoreApplication.translate(
                "OutputStatus",
                "Check the commands in the table against your overlay's API "
                "description, and clear the command of fields the overlay doesn't "
                "use: every call counts against your daily limit.",
            ),
        )
    if code >= 500:
        if key == VMIX:
            hint = QCoreApplication.translate(
                "OutputStatus",
                "Check the Input and the vMix field names in the table (for "
                "example Home Score.Text).",
            )
        else:
            hint = ""
        if server:
            hint = " ".join(
                part
                for part in (
                    QCoreApplication.translate(
                        "OutputStatus", "It answered: {text}"
                    ).format(text=elide_middle(server, 120)),
                    hint,
                )
                if part
            )
        return Problem(
            ERROR,
            QCoreApplication.translate(
                "OutputStatus", "HTTP {code}: the receiver reported an error"
            ).format(code=code),
            hint,
        )
    return Problem(
        ERROR,
        QCoreApplication.translate("OutputStatus", "HTTP {code}").format(code=code),
        QCoreApplication.translate("OutputStatus", "It answered: {text}").format(
            text=elide_middle(server, 120)
        )
        if server
        else "",
    )


def worker_problem(
    key: str,
    worker: WorkerStatus | None,
    target: str | None,
    secrets: Iterable[str] = (),
) -> Problem | None:
    """The problem a worker's status shows, or None if it is fine."""
    if worker is None or worker.last_error is None:
        return None
    if not (worker.retrying or worker.failing_keys):
        return None
    problem = describe_error(key, worker.last_error, target, secrets)
    if worker.retrying:
        if problem.state == ERROR:  # e.g. vMix's TCP API port: needs action
            return problem
        hint = problem.hint
        # the time left until the next try (or the whole wait, if unknown)
        wait = worker.retry_in if worker.retry_in is not None else worker.retry_delay
        if _is_a(worker.last_error, RetryLater) and wait is not None:
            # the endpoint said how long to wait (e.g. until a quota resets)
            hint = " ".join(
                part
                for part in (
                    hint,
                    QCoreApplication.translate(
                        "OutputStatus", "Next try in {wait}."
                    ).format(wait=wait_text(wait)),
                )
                if part
            )
        return Problem(RETRYING, problem.detail, hint)
    if worker.ok_keys:
        # some fields arrive, others don't
        total = worker.ok_keys + worker.failing_keys
        return Problem(
            WARNING,
            QCoreApplication.translate(
                "OutputStatus", "{failing} of {total} failing: {problem}"
            ).format(failing=worker.failing_keys, total=total, problem=problem.detail),
            problem.hint,
        )
    return problem


def _technical(worker: WorkerStatus | None, secrets: Iterable[str] = ()) -> str:
    if worker is None or worker.last_error is None:
        return ""
    return elide_middle(redact(str(worker.last_error), secrets), 300)


def _with_problem(
    status: DestinationStatus, problem: Problem | None, technical: str = ""
) -> DestinationStatus:
    if problem is None:
        return status
    return DestinationStatus(
        key=status.key,
        state=problem.state,
        detail=problem.detail,
        enabled=status.enabled,
        switchable=status.switchable,
        hint=problem.hint,
        last_activity_at=status.last_activity_at,
        activity=status.activity,
        technical=technical,
    )


# --- the destinations ---------------------------------------------------------


def files_status(
    folder: str | None,
    files: FileOutputStatus | None,
    lost_folder: str | None = None,
) -> DestinationStatus:
    """Text files: on while an output folder is set."""
    files = files or FileOutputStatus()
    if not folder:
        if lost_folder:
            return DestinationStatus(
                FILES,
                ERROR,
                QCoreApplication.translate(
                    "OutputStatus", "Folder not found: {folder}"
                ).format(folder=elide_middle(lost_folder)),
                hint=QCoreApplication.translate(
                    "OutputStatus",
                    "The output folder {folder} doesn't exist any more, so no files "
                    "are written. Choose a folder to write them again.",
                ).format(folder=lost_folder),
            )
        return DestinationStatus(
            FILES,
            OFF,
            QCoreApplication.translate("OutputStatus", "Off"),
            hint=QCoreApplication.translate(
                "OutputStatus", "Choose a folder to write the readings to files."
            ),
        )
    shown_folder = elide_middle(folder, 72)
    written = files.last_write_at if files.folder == folder else None
    base = DestinationStatus(
        FILES,
        SENDING,
        QCoreApplication.translate(
            "OutputStatus", "Waiting for readings to write to {folder}"
        ).format(folder=shown_folder),
        enabled=True,
        last_activity_at=written,
        activity=ACTIVITY_WRITTEN,
    )
    if files.folder == folder and files.failing:
        if len(files.failing) == 1:
            detail = QCoreApplication.translate(
                "OutputStatus", "Can't write {file}"
            ).format(file=files.failing[0])
        else:
            detail = QCoreApplication.translate(
                "OutputStatus", "Can't write {file} and {count} more"
            ).format(file=files.failing[0], count=len(files.failing) - 1)
        return DestinationStatus(
            FILES,
            ERROR,
            detail,
            enabled=True,
            hint=QCoreApplication.translate(
                "OutputStatus",
                "Check that the folder can be written to and that no other "
                "program locks the files. ScoreSight tries again at every save.",
            ),
            last_activity_at=written,
            activity=ACTIVITY_WRITTEN,
            technical=files.last_error or "",
        )
    if written is None:
        return base
    if files.files == 1:
        detail = QCoreApplication.translate(
            "OutputStatus", "Writing to {folder} · 1 file"
        ).format(folder=shown_folder)
    else:
        detail = QCoreApplication.translate(
            "OutputStatus", "Writing to {folder} · {count} files"
        ).format(folder=shown_folder, count=files.files)
    return DestinationStatus(
        FILES,
        OK,
        detail,
        enabled=True,
        hint=QCoreApplication.translate(
            "OutputStatus",
            "The files are in {folder}. A file is written when its value changes.",
        ).format(folder=folder),
        last_activity_at=written,
        activity=ACTIVITY_WRITTEN,
    )


def http_status(
    port: int | None,
    requested_port: int | None,
    urls: tuple[str, ...],
    stats: HttpServerStats | None,
) -> DestinationStatus:
    """The HTTP server: always on (no switch); not running if its port was
    busy."""
    stats = stats or HttpServerStats()
    if port is None:
        return DestinationStatus(
            HTTP,
            ERROR,
            QCoreApplication.translate(
                "OutputStatus", "Not running: port {port} is in use"
            ).format(port=requested_port),
            enabled=True,
            switchable=False,
            hint=QCoreApplication.translate(
                "OutputStatus",
                "Another program (or another ScoreSight) uses port {port}. Close "
                "it, or start ScoreSight with --port to use another port.",
            ).format(port=requested_port),
            technical=stats.start_error or "",
        )
    url = urls[0] if urls else f"http://localhost:{port}"
    if stats.requests == 0:
        detail = QCoreApplication.translate(
            "OutputStatus", "{url} · no requests yet"
        ).format(url=url)
    elif stats.recent_clients == 1:
        detail = QCoreApplication.translate("OutputStatus", "{url} · 1 client").format(
            url=url
        )
    elif stats.recent_clients > 1:
        detail = QCoreApplication.translate(
            "OutputStatus", "{url} · {count} clients"
        ).format(url=url, count=stats.recent_clients)
    else:
        detail = QCoreApplication.translate(
            "OutputStatus", "{url} · no recent requests"
        ).format(url=url)
    return DestinationStatus(
        HTTP,
        OK,
        detail,
        enabled=True,
        switchable=False,
        hint=QCoreApplication.translate(
            "OutputStatus",
            "Always on. Open {url}/scoresight in a browser, or read {url}/json, "
            "/xml or /csv from other software.",
        ).format(url=url),
        last_activity_at=stats.last_request_at,
        activity=ACTIVITY_REQUEST,
    )


def obs_status(
    address: str | None,
    connecting_to: str | None,
    connect_error: ErrorInfo | None,
    worker: WorkerStatus | None,
    connected_at: float | None = None,
    has_sources: bool = True,
    connect_target: str | None = None,
) -> DestinationStatus:
    """OBS: on while connected (address is "host:port" of the connection).
    connect_error is why the last attempt to connect (to connect_target)
    failed."""
    if address is None:
        if connecting_to:
            return DestinationStatus(
                OBS,
                SENDING,
                QCoreApplication.translate(
                    "OutputStatus", "Connecting to {target}…"
                ).format(target=connecting_to),
                enabled=True,
            )
        if connect_error is not None:
            problem = describe_error(OBS, connect_error, connect_target)
            return DestinationStatus(
                OBS,
                ERROR,
                QCoreApplication.translate(
                    "OutputStatus", "Not connected: {problem}"
                ).format(problem=problem.detail),
                hint=" ".join(
                    part
                    for part in (
                        problem.hint,
                        QCoreApplication.translate(
                            "OutputStatus", "Then click Connect OBS."
                        ),
                    )
                    if part
                ),
                technical=str(connect_error),
            )
        return DestinationStatus(
            OBS,
            OFF,
            QCoreApplication.translate("OutputStatus", "Not connected"),
            hint=QCoreApplication.translate(
                "OutputStatus",
                "Click Connect OBS to update text sources in OBS Studio.",
            ),
        )
    last_sent = worker.last_success_at if worker is not None else None
    if last_sent is not None and connected_at is not None and last_sent < connected_at:
        last_sent = None  # sent over an earlier connection
    status = DestinationStatus(
        OBS,
        OK,
        QCoreApplication.translate("OutputStatus", "Connected to {target}").format(
            target=address
        ),
        enabled=True,
        hint=QCoreApplication.translate(
            "OutputStatus", "A text source is updated when its field's value changes."
        ),
        last_activity_at=last_sent,
    )
    problem = worker_problem(OBS, worker, address)
    if problem is not None and worker is not None and worker.retrying:
        problem = Problem(
            RETRYING,
            QCoreApplication.translate(
                "OutputStatus", "Reconnecting to OBS at {target}…"
            ).format(target=address),
            QCoreApplication.translate(
                "OutputStatus",
                "The connection to OBS was lost. ScoreSight reconnects by itself "
                "as soon as OBS is reachable again.",
            ),
        )
    if problem is None and not has_sources:
        problem = Problem(
            WARNING,
            QCoreApplication.translate(
                "OutputStatus", "Connected, but no field has an OBS text source"
            ),
            QCoreApplication.translate(
                "OutputStatus",
                "The standard fields update OBS text sources with their names "
                "(Home score, Clock...). Place them on the picture.",
            ),
        )
    return _with_problem(status, problem, _technical(worker))


def vmix_status(
    running: bool,
    host: str,
    port: str,
    input_number: str,
    mapping: Mapping[str, str] | None,
    worker: WorkerStatus | None,
) -> DestinationStatus:
    """vMix: on while started (Start vMix)."""
    target = f"{host or '?'}:{port or '?'}"
    if not running:
        return DestinationStatus(
            VMIX,
            OFF,
            QCoreApplication.translate("OutputStatus", "Off"),
            hint=QCoreApplication.translate(
                "OutputStatus", "Click Start vMix to update input {input} at {target}."
            ).format(input=input_number or "?", target=target),
        )
    if not any((mapping or {}).values()):
        return DestinationStatus(
            VMIX,
            WARNING,
            QCoreApplication.translate("OutputStatus", "No fields to send"),
            enabled=True,
            hint=QCoreApplication.translate(
                "OutputStatus",
                "Place fields on the picture and enter their vMix field names (for "
                "example Home Score.Text) in the table.",
            ),
        )
    last_sent = worker.last_success_at if worker is not None else None
    if last_sent is None:
        status = DestinationStatus(
            VMIX,
            SENDING,
            QCoreApplication.translate(
                "OutputStatus", "Waiting for a new value for {target}, input {input}"
            ).format(target=target, input=input_number or "?"),
            enabled=True,
            hint=QCoreApplication.translate(
                "OutputStatus",
                "vMix gets a field's value when it changes (or every time, with "
                "“Also resend unchanged values”).",
            ),
        )
    else:
        status = DestinationStatus(
            VMIX,
            OK,
            QCoreApplication.translate(
                "OutputStatus", "Sending to {target}, input {input}"
            ).format(target=target, input=input_number or "?"),
            enabled=True,
            hint=QCoreApplication.translate(
                "OutputStatus",
                "vMix gets a field's value when it changes (or every time, with "
                "“Also resend unchanged values”).",
            ),
            last_activity_at=last_sent,
        )
    return _with_problem(
        status, worker_problem(VMIX, worker, target), _technical(worker)
    )


def _daily_calls_text(quota) -> str:
    """ "9512 calls left today", from overlays.uno's headers, or "". (No
    thousands separator: "9,512" reads as a decimal in many languages.)"""
    daily = getattr(quota, "daily", None)
    if daily is None or daily.remaining is None:
        return ""
    return QCoreApplication.translate(
        "OutputStatus", "{calls} calls left today"
    ).format(calls=str(daily.remaining))


def uno_status(
    running: bool,
    endpoint: str | None,
    mapping: Mapping[str, str] | None,
    worker: WorkerStatus | None,
    quota=None,
) -> DestinationStatus:
    """UNO: on while started (Start sending). The URL is a secret: only its
    host is shown. quota (uno_output.UnoQuota) holds the limits overlays.uno
    reported: the daily calls left are shown, with a warning when few are."""
    secrets = url_secrets(endpoint, path_is_secret=True)
    host = url_target(endpoint)
    if not running:
        return DestinationStatus(
            UNO,
            OFF,
            QCoreApplication.translate("OutputStatus", "Off"),
            hint=QCoreApplication.translate(
                "OutputStatus",
                "Click Start sending to drive your overlays.uno overlay.",
            ),
        )
    if not endpoint or UNO_PLACEHOLDER_MARK in endpoint or host is None:
        return DestinationStatus(
            UNO,
            WARNING,
            QCoreApplication.translate("OutputStatus", "Enter your UNO API URL"),
            enabled=True,
            hint=QCoreApplication.translate(
                "OutputStatus",
                "Copy the API URL of your overlay's control app in overlays.uno into "
                "URL.",
            ),
        )
    if not any((mapping or {}).values()):
        return DestinationStatus(
            UNO,
            WARNING,
            QCoreApplication.translate("OutputStatus", "No fields to send"),
            enabled=True,
            hint=QCoreApplication.translate(
                "OutputStatus",
                "Place fields on the picture and enter the UNO commands in the table.",
            ),
        )
    # fields without a command (since custom fields get none by default)
    unmapped = sum(1 for command in (mapping or {}).values() if not command)
    hint = (
        QCoreApplication.translate(
            "OutputStatus",
            "{count} field(s) have no UNO command and aren't sent: enter one in "
            "the table if the overlay has a command for them.",
        ).format(count=unmapped)
        if unmapped
        else ""
    )
    last_sent = worker.last_success_at if worker is not None else None
    if last_sent is None:
        status = DestinationStatus(
            UNO,
            SENDING,
            QCoreApplication.translate(
                "OutputStatus", "Waiting for a new value for {host}"
            ).format(host=host),
            enabled=True,
            hint=hint,
        )
    else:
        detail = QCoreApplication.translate("OutputStatus", "Sending to {host}").format(
            host=host
        )
        calls_left = _daily_calls_text(quota)
        if calls_left:
            detail = f"{detail} · {calls_left}"
        status = DestinationStatus(
            UNO, OK, detail, enabled=True, hint=hint, last_activity_at=last_sent
        )
    problem = worker_problem(UNO, worker, host, secrets)
    if problem is None and getattr(quota, "daily_low", False):
        problem = Problem(
            WARNING,
            QCoreApplication.translate(
                "OutputStatus", "Only {calls} overlays.uno calls left today"
            ).format(calls=str(quota.daily.remaining)),
            QCoreApplication.translate(
                "OutputStatus",
                "Every update is a call. When none are left, overlays.uno refuses "
                "updates until the limit resets; ScoreSight then sends the latest "
                "values. To use fewer calls, keep “Also resend unchanged values” "
                "off and clear the command of fields the overlay doesn't use.",
            ),
        )
    return _with_problem(status, problem, _technical(worker, secrets))


def api_status(
    enabled: bool,
    url: str | None,
    method: str,
    encoding: str,
    worker: WorkerStatus | None,
    mode=None,
) -> DestinationStatus:
    """The outbound HTTP API: on while its checkbox is ticked. mode
    (api_output.SendMode) tells how the readings are sent."""
    url = (url or "").strip()
    secrets = url_secrets(url)
    target = url_target(url)
    if not enabled:
        return DestinationStatus(
            API,
            OFF,
            QCoreApplication.translate("OutputStatus", "Off"),
            hint=QCoreApplication.translate(
                "OutputStatus",
                "Tick the checkbox to send the readings to a URL on every "
                "detection cycle.",
            ),
        )
    if not url:
        return DestinationStatus(
            API,
            WARNING,
            QCoreApplication.translate("OutputStatus", "Enter a URL"),
            enabled=True,
            hint=QCoreApplication.translate(
                "OutputStatus",
                "Enter the URL to send the readings to, for example "
                "http://192.168.1.10:8091/scores.",
            ),
        )
    if target is None or "://" not in url:
        return DestinationStatus(
            API,
            WARNING,
            QCoreApplication.translate("OutputStatus", "The URL isn't valid"),
            enabled=True,
            hint=QCoreApplication.translate(
                "OutputStatus",
                "The URL needs a scheme and a host, for example "
                "http://192.168.1.10:8091/scores.",
            ),
        )
    if getattr(mode, "needs_address", False):
        return DestinationStatus(
            API,
            WARNING,
            QCoreApplication.translate(
                "OutputStatus", "Enter your device's address in the URL"
            ),
            enabled=True,
            hint=QCoreApplication.translate(
                "OutputStatus",
                "Replace the capitalized placeholder in the URL (for example "
                "TRICASTER-IP) with the device's IP address, and the login with "
                "its user name and password.",
            ),
        )
    if method == "GET":
        what = QCoreApplication.translate("OutputStatus", "GET to {target}").format(
            target=target
        )
    else:
        what = QCoreApplication.translate(
            "OutputStatus", "{method} {encoding} to {target}"
        ).format(method=method, encoding=encoding, target=target)
    how = []
    if getattr(mode, "per_field", False):
        fields = mode.fields_per_request
        if fields == 1:
            how.append(
                QCoreApplication.translate("OutputStatus", "a request per field")
            )
        elif fields:
            how.append(
                QCoreApplication.translate(
                    "OutputStatus", "up to {fields} fields a request"
                ).format(fields=fields)
            )
    if getattr(mode, "only_changes", False):
        how.append(QCoreApplication.translate("OutputStatus", "only changes"))
    if how:
        what = " · ".join([what, *how])
    last_sent = worker.last_success_at if worker is not None else None
    if last_sent is None:
        status = DestinationStatus(
            API,
            SENDING,
            QCoreApplication.translate(
                "OutputStatus", "Waiting for readings: {request}"
            ).format(request=what),
            enabled=True,
        )
    else:
        status = DestinationStatus(
            API, OK, what, enabled=True, last_activity_at=last_sent
        )
    return _with_problem(
        status,
        worker_problem(API, worker, target, secrets),
        _technical(worker, secrets),
    )


def tcp_status(
    running: bool,
    config: TcpConfig,
    product: str,
    has_fields: bool,
    worker: WorkerStatus | None,
    connection: ConnectionStatus | None,
) -> DestinationStatus:
    """The TCP / UDP output: on while started (Start sending). product is the
    preset's product ("CasparCG"...), "" for a custom protocol."""
    connection = connection or ConnectionStatus()
    if config.listens:
        return _tcp_server_status(
            running, config, product, has_fields, worker, connection
        )
    target = config.target
    transport = {UDP: "UDP", WEBSOCKET: "WebSocket"}.get(config.transport, "TCP")
    if not running:
        return DestinationStatus(
            TCP,
            OFF,
            QCoreApplication.translate("OutputStatus", "Off"),
            hint=QCoreApplication.translate(
                "OutputStatus",
                "Click Start sending to send the readings over {transport} to "
                "{target}.",
            ).format(transport=transport, target=target),
        )
    if not config.is_complete and config.websocket:
        return DestinationStatus(
            TCP,
            WARNING,
            QCoreApplication.translate("OutputStatus", "Enter a ws:// or wss:// URL"),
            enabled=True,
            hint=QCoreApplication.translate(
                "OutputStatus",
                "Enter the WebSocket address of the receiving server, for example "
                "wss://example.com/scores.",
            ),
        )
    if not config.is_complete:
        return DestinationStatus(
            TCP,
            WARNING,
            QCoreApplication.translate("OutputStatus", "Enter the host and port"),
            enabled=True,
            hint=QCoreApplication.translate(
                "OutputStatus",
                "Enter the address of the receiving program's computer and the "
                "port it listens on (set in that program).",
            ),
        )
    if not has_fields:
        return DestinationStatus(
            TCP,
            WARNING,
            QCoreApplication.translate("OutputStatus", "No fields to send"),
            enabled=True,
            hint=QCoreApplication.translate(
                "OutputStatus",
                "Place fields on the picture and give them names in the table (an "
                "empty name leaves a field out).",
            ),
        )
    last_sent = worker.last_success_at if worker is not None else None
    if config.transport == UDP:
        if last_sent is None:
            status = DestinationStatus(
                TCP,
                SENDING,
                QCoreApplication.translate(
                    "OutputStatus", "Waiting for readings to send to {target} (UDP)"
                ).format(target=target),
                enabled=True,
            )
        else:
            status = DestinationStatus(
                TCP,
                OK,
                _with_product(
                    product,
                    QCoreApplication.translate(
                        "OutputStatus", "Sending to {target} (UDP)"
                    ).format(target=target),
                ),
                enabled=True,
                hint=QCoreApplication.translate(
                    "OutputStatus",
                    "UDP has no connection: ScoreSight can't tell whether the "
                    "values arrive.",
                ),
                last_activity_at=last_sent,
            )
        return _with_problem(
            status, worker_problem(TCP, worker, target), _technical(worker)
        )

    problem = worker_problem(TCP, worker, target)
    if problem is None and connection.quick_closes >= 2:
        if config.websocket:
            hint = QCoreApplication.translate(
                "OutputStatus",
                "The server accepts the WebSocket, then closes it: check the URL's "
                "path and the token (in Headers or in the URL). ScoreSight "
                "connects again, waiting a little longer each time.",
            )
        else:
            hint = QCoreApplication.translate(
                "OutputStatus",
                "Check the port: it must be the receiving program's input for this "
                "protocol (not, for example, a web server's port). ScoreSight "
                "connects again, waiting a little longer each time.",
            )
        problem = Problem(
            WARNING,
            QCoreApplication.translate(
                "OutputStatus", "{target} closes the connection right away"
            ).format(target=target),
            hint,
        )
    if not connection.connected:
        status = DestinationStatus(
            TCP,
            SENDING,
            QCoreApplication.translate(
                "OutputStatus", "Connecting to {target}…"
            ).format(target=target),
            enabled=True,
        )
        return _with_problem(status, problem, _technical(worker))
    if (
        last_sent is not None
        and connection.connected_at is not None
        and last_sent < connection.connected_at
    ):
        last_sent = None  # sent over an earlier connection
    if connection.last_reply:
        hint = QCoreApplication.translate(
            "OutputStatus", "Last answer: {reply}"
        ).format(reply=elide_middle(connection.last_reply, 120))
    else:
        hint = QCoreApplication.translate(
            "OutputStatus",
            "A field's value is sent when it changes (or every time, with “Also "
            "resend unchanged values”).",
        )
    status = DestinationStatus(
        TCP,
        OK,
        _with_product(
            product,
            QCoreApplication.translate("OutputStatus", "Connected to {target}").format(
                target=target
            ),
        ),
        enabled=True,
        hint=hint,
        last_activity_at=last_sent,
    )
    if problem is None and connection.reply_error:
        if config.preset == CASPARCG:
            reply_hint = QCoreApplication.translate(
                "OutputStatus",
                "Check the template's name (it must be in CasparCG's templates "
                "folder), the channel and the layer.",
            )
        else:
            reply_hint = QCoreApplication.translate(
                "OutputStatus",
                "The receiving program reported an error: check the template and "
                "the names in the table.",
            )
        return _with_problem(
            status,
            Problem(
                WARNING,
                QCoreApplication.translate(
                    "OutputStatus", "{target} answered “{reply}”"
                ).format(target=target, reply=elide_middle(connection.reply_error, 60)),
                reply_hint,
            ),
            connection.reply_error,
        )
    return _with_problem(status, problem, _technical(worker))


def _tcp_server_status(
    running: bool,
    config: TcpConfig,
    product: str,
    has_fields: bool,
    worker: WorkerStatus | None,
    connection: ConnectionStatus,
) -> DestinationStatus:
    """The TCP / UDP output as a TCP server: other programs connect to
    ScoreSight's port and get the readings."""
    port = config.port if config.port is not None else "?"
    if not running:
        return DestinationStatus(
            TCP,
            OFF,
            QCoreApplication.translate("OutputStatus", "Off"),
            hint=QCoreApplication.translate(
                "OutputStatus",
                "Click Start sending to let other programs connect to ScoreSight "
                "on port {port} and get the readings.",
            ).format(port=port),
        )
    if config.port is None:
        return DestinationStatus(
            TCP,
            WARNING,
            QCoreApplication.translate("OutputStatus", "Enter a port"),
            enabled=True,
            hint=QCoreApplication.translate(
                "OutputStatus",
                "Enter the port ScoreSight listens on, and the same port in the "
                "program that connects to ScoreSight.",
            ),
        )
    if not has_fields:
        return DestinationStatus(
            TCP,
            WARNING,
            QCoreApplication.translate("OutputStatus", "No fields to send"),
            enabled=True,
            hint=QCoreApplication.translate(
                "OutputStatus",
                "Place fields on the picture and give them names in the table (an "
                "empty name leaves a field out).",
            ),
        )
    if worker is not None and worker.last_error is not None:
        if worker.retrying and _is_a(worker.last_error, ListenError):
            return DestinationStatus(
                TCP,
                ERROR,
                QCoreApplication.translate(
                    "OutputStatus", "Can't listen on port {port}"
                ).format(port=port),
                enabled=True,
                hint=QCoreApplication.translate(
                    "OutputStatus",
                    "Another program uses this port, or the system doesn't allow "
                    "it. Choose another port (and set it in the program that "
                    "connects). ScoreSight tries again by itself.",
                ),
                technical=_technical(worker),
            )
    if not connection.listening:
        return DestinationStatus(
            TCP,
            SENDING,
            QCoreApplication.translate("OutputStatus", "Opening port {port}…").format(
                port=port
            ),
            enabled=True,
        )
    if not connection.clients:
        return DestinationStatus(
            TCP,
            SENDING,
            _with_product(
                product,
                QCoreApplication.translate(
                    "OutputStatus", "Listening on port {port} · nothing connected"
                ).format(port=port),
            ),
            enabled=True,
            hint=QCoreApplication.translate(
                "OutputStatus",
                "Waiting for a program to connect to this computer's address, port "
                "{port}. Allow ScoreSight through this computer's firewall for "
                "programs on other computers.",
            ).format(port=port),
        )
    count = len(connection.clients)
    if count == 1:
        detail = QCoreApplication.translate(
            "OutputStatus", "Listening on port {port} · 1 program connected"
        ).format(port=port)
    else:
        detail = QCoreApplication.translate(
            "OutputStatus", "Listening on port {port} · {count} programs connected"
        ).format(port=port, count=count)
    hint = QCoreApplication.translate("OutputStatus", "Connected: {programs}").format(
        programs=elide_middle(", ".join(connection.clients), 160)
    )
    if connection.last_reply:
        hint += " " + QCoreApplication.translate(
            "OutputStatus", "Last answer: {reply}"
        ).format(reply=elide_middle(connection.last_reply, 120))
    last_sent = worker.last_success_at if worker is not None else None
    return DestinationStatus(
        TCP,
        OK,
        _with_product(product, detail),
        enabled=True,
        hint=hint,
        last_activity_at=last_sent,
    )


def _with_product(product: str, detail: str) -> str:
    """ "CasparCG: Connected to localhost:5250" (detail alone without one)."""
    if not product:
        return detail
    return QCoreApplication.translate("OutputStatus", "{product}: {detail}").format(
        product=product, detail=detail
    )
