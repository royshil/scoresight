"""output_status: what the window says about each output destination, and the
plain messages for the documented failure modes."""

import socket

import pytest
import requests
from obsws_python.error import OBSSDKError, OBSSDKRequestError

import output_status
from file_output import FileOutputStatus
from http_server import HttpServerStats
from obs_websocket import OBSConnectionLost
from output_status import (
    API,
    ERROR,
    FILES,
    HTTP,
    OBS,
    OFF,
    OK,
    RETRYING,
    SENDING,
    UNO,
    VMIX,
    WARNING,
    DestinationStatus,
    accessible_text,
    age_text,
    describe_error,
    redact,
    status_tooltip,
    url_secrets,
    url_target,
    worker_problem,
)
from output_worker import ErrorInfo, OutputError, RetryLater, WorkerStatus
from vmix_output import VMixTCPPortError

TOKEN = "f4b1c2d3e4f5a6b7c8d9"
UNO_URL = f"https://app.overlays.uno/apiv2/controlapps/{TOKEN}/api"

REFUSED = (
    "HTTPConnectionPool(host='192.168.1.40', port=8088): Max retries exceeded with "
    "url: /api/?Function=SetText (Caused by NewConnectionError('<HTTPConnection>: "
    "Failed to establish a new connection: [WinError 10061] No connection could be "
    "made because the target machine actively refused it'))"
)


def unreachable(error_type, message=""):
    return ErrorInfo(error_type, message, unreachable=True)


def http_error(code, description="SetText 'Home Score.Text'", body=""):
    message = f"{description} returned HTTP {code}" + (f": {body}" if body else "")
    return ErrorInfo(OutputError, message, code=code)


# --- the documented failure modes -----------------------------------------------


@pytest.mark.parametrize(
    "error",
    [
        unreachable(
            VMixTCPPortError,
            "127.0.0.1:8099 answered like the vMix TCP API ('VERSION OK').",
        ),
        unreachable(
            requests.ConnectionError,
            "('Connection aborted.', BadStatusLine('VERSION OK 26.0.0.45\\r\\n'))",
        ),
    ],
)
def test_vmix_on_its_tcp_api_port(error):
    problem = describe_error(VMIX, error, "127.0.0.1:8099")
    assert problem.state == ERROR  # retried, but only the user can fix it
    assert problem.detail == "Port 8099 is vMix's TCP API: use 8088"
    assert "Web Controller" in problem.hint


def test_vmix_asks_for_a_login():
    problem = describe_error(VMIX, http_error(401), "vmix-pc:8088")
    assert problem.state == ERROR
    assert problem.detail == "HTTP 401: vMix asks for a login"
    assert "without login" in problem.hint


def test_uno_url_refused_and_rate_limit():
    problem = describe_error(UNO, http_error(403, "UNO SetGoalsHome"), "uno")
    assert problem.detail == "HTTP 403: check the UNO URL"
    assert "Copy the API URL" in problem.hint

    problem = describe_error(UNO, http_error(429, "UNO SetGoalsHome"), "uno")
    assert problem.state == WARNING
    assert problem.detail == "HTTP 429: overlays.uno's call limit reached"
    assert "Also resend unchanged values" in problem.hint
    assert "keeps the latest value" in problem.hint  # no longer dropped

    # kept for a retry (RetryLater): says so
    retried = ErrorInfo(RetryLater, "UNO x returned HTTP 429", 429, unreachable=True)
    problem = describe_error(UNO, retried, "uno")
    assert problem.detail == "HTTP 429: overlays.uno's call limit reached · retrying"
    problem = describe_error(API, retried, "h")
    assert problem.detail == "HTTP 429: too many requests · retrying"
    assert "Only changes" in problem.hint

    problem = describe_error(UNO, http_error(400, "UNO Shot Clock"), "uno")
    assert problem.detail == "HTTP 400: overlays.uno doesn't know a command"


def test_retry_later_wait_is_in_the_hint():
    worker = WorkerStatus(
        "UNO",
        retrying=True,
        retry_delay=125.0,
        last_error=ErrorInfo(RetryLater, "UNO x returned HTTP 429", 429, True),
    )
    problem = output_status.worker_problem(UNO, worker, "uno")
    assert problem.state == RETRYING
    assert problem.hint.endswith("Next try in 3 min.")


@pytest.mark.parametrize(
    "seconds, text",
    [
        (0, "a few seconds"),
        (4.4, "a few seconds"),
        (42, "42 s"),
        (61, "2 min"),
        (3600, "1 h"),
        (3601, "2 h"),
    ],
)
def test_wait_text(seconds, text):
    assert output_status.wait_text(seconds) == text


def test_api_error_statuses():
    assert describe_error(API, http_error(404, "POST x"), "h").detail == (
        "HTTP 404: check the URL"
    )
    assert describe_error(API, http_error(401, "POST x"), "h").detail == (
        "HTTP 401: access denied"
    )
    problem = describe_error(API, http_error(500, "POST x", "Internal Error"), "h")
    assert problem.detail == "HTTP 500: the receiver reported an error"
    assert "Internal Error" in problem.hint
    assert describe_error(API, http_error(418, "POST x"), "h").detail == "HTTP 418"


def test_connection_refused():
    problem = describe_error(
        VMIX, unreachable(requests.ConnectionError, REFUSED), "192.168.1.40:8088"
    )
    assert problem.state == RETRYING
    assert problem.detail == "Can't reach 192.168.1.40:8088 · retrying"
    assert "Web Controller" in problem.hint and "8088" in problem.hint


def test_no_answer_and_unknown_host():
    problem = describe_error(
        API,
        unreachable(requests.ConnectTimeout, "Connection to 10.0.0.9 timed out."),
        "10.0.0.9:8091",
    )
    assert problem.detail == "No answer from 10.0.0.9:8091 · retrying"
    assert "firewall" in problem.hint and "8091" in problem.hint

    problem = describe_error(
        VMIX,
        unreachable(
            requests.ConnectionError,
            "Failed to resolve 'vmixpc' ([Errno 11001] getaddrinfo failed)",
        ),
        "vmixpc:8088",
    )
    assert problem.detail == "Can't find vmixpc · retrying"


def test_obs_connection_failures():
    no_password = ErrorInfo(
        OBSSDKError, "authentication enabled but no password provided"
    )
    assert describe_error(OBS, no_password, "localhost:4455").detail == (
        "OBS needs a password"
    )
    wrong_password = ErrorInfo(
        OBSSDKError,
        "failed to identify client with the server, please check connection settings",
    )
    problem = describe_error(OBS, wrong_password, "localhost:4455")
    assert problem.detail == "OBS refused the connection: check the password"
    assert "Show Connect Info" in problem.hint

    refused = ErrorInfo(
        ConnectionRefusedError, "[WinError 10061] No connection could be made"
    )
    problem = describe_error(OBS, refused, "localhost:4455")
    assert problem.detail == "Can't reach localhost:4455"
    assert "WebSocket server" in problem.hint

    timeout = ErrorInfo(socket.timeout, "timed out")
    assert describe_error(OBS, timeout, "obs-pc:4455").detail == (
        "No answer from obs-pc:4455"
    )


def test_obs_missing_text_source():
    error = ErrorInfo(
        OBSSDKRequestError,
        "Request SetInputSettings returned code 600. With message: No source was "
        "found by the name of `Clock`.",
        code=600,
    )
    problem = describe_error(OBS, error, "localhost:4455")
    assert problem.detail == "OBS has no text source “Clock”"
    assert "Create OBS Scene" in problem.hint


def test_obs_lost_connection():
    error = unreachable(
        OBSConnectionLost, "connection to OBS at localhost:4455 lost, reconnecting"
    )
    problem = describe_error(OBS, error, "localhost:4455")
    assert problem.state == RETRYING
    assert problem.detail == "Lost the connection to OBS at localhost:4455 · retrying"


def test_errors_retrying_does_not_fix():
    tls = unreachable(
        requests.exceptions.SSLError,
        "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed",
    )
    problem = describe_error(API, tls, "hooks.example.com")
    assert (problem.state, problem.detail) == (
        ERROR,
        "No secure connection to hooks.example.com",
    )
    problem = worker_problem(
        API, WorkerStatus("Output API", retrying=True, last_error=tls), "h"
    )
    assert problem.state == ERROR  # retried, but only the user can fix it

    invalid = ErrorInfo(requests.exceptions.InvalidURL, "Invalid URL 'http://'")
    assert describe_error(API, invalid, "?").detail == "The URL isn't valid"


def test_other_errors_are_shown_shortened():
    problem = describe_error(API, ErrorInfo(ValueError, "x" * 200), "h")
    assert problem.state == ERROR
    assert problem.detail.startswith("ValueError: x") and len(problem.detail) <= 70


# --- secrets ----------------------------------------------------------------------


def test_the_uno_token_and_api_keys_are_never_shown():
    secrets = url_secrets(UNO_URL, path_is_secret=True)
    text = f"HTTPSConnectionPool(host='app.overlays.uno'): url: /apiv2/controlapps/{TOKEN}/api"
    assert TOKEN not in redact(text, secrets)
    assert url_target(UNO_URL) == "app.overlays.uno"

    api_url = "https://user:pa55@example.com:8443/hook?token=SECRET"
    secrets = url_secrets(api_url)
    shown = redact(f"POST {api_url} returned HTTP 500", secrets)
    assert "SECRET" not in shown and "pa55" not in shown
    assert url_target(api_url) == "example.com:8443"

    # a webhook key in the path
    webhook = "https://hooks.example.com/services/T0001/B0002/XyZ123456789AbCdEf0123"
    shown = redact(f"GET {webhook} returned HTTP 404", url_secrets(webhook))
    assert "XyZ123456789AbCdEf0123" not in shown
    assert "/services/T0001/B0002/" in shown  # short segments stay readable


def test_uno_status_hides_the_token():
    worker = WorkerStatus(
        "UNO",
        failed=1,
        consecutive_failures=1,
        retrying=True,
        last_failure_at=1.0,
        last_error=unreachable(
            requests.ConnectionError,
            f"HTTPSConnectionPool(host='app.overlays.uno', port=443): Max retries "
            f"exceeded with url: /apiv2/controlapps/{TOKEN}/api (Caused by "
            f"NewConnectionError('Failed to establish a new connection: [Errno 111] "
            f"Connection refused'))",
        ),
    )
    status = output_status.uno_status(True, UNO_URL, {"Time": "SetMatchTime"}, worker)
    assert status.state == RETRYING
    assert status.detail == "Can't reach app.overlays.uno · retrying"
    for text in (
        status.detail,
        status.hint,
        status.technical,
        status_tooltip(status, 2),
    ):
        assert TOKEN not in text


# --- the workers' problems ------------------------------------------------------


def test_some_fields_failing_is_a_warning():
    worker = WorkerStatus(
        "vMix",
        sent=10,
        failed=3,
        ok_keys=3,
        failing_keys=1,
        last_success_at=5.0,
        last_error=http_error(500, body="Field not found"),
    )
    problem = worker_problem(VMIX, worker, "localhost:8088")
    assert problem.state == WARNING
    assert problem.detail == (
        "1 of 4 failing: HTTP 500: the receiver reported an error"
    )
    assert "Field not found" in problem.hint


def test_a_healthy_worker_has_no_problem():
    assert worker_problem(VMIX, WorkerStatus("vMix", sent=3), "h") is None
    assert worker_problem(VMIX, None, "h") is None


# --- the destinations -------------------------------------------------------------


def test_files_status():
    assert output_status.files_status(None, None).state == OFF
    lost = output_status.files_status(None, None, lost_folder=r"D:\Scores")
    assert (lost.state, lost.enabled) == (ERROR, False)
    assert lost.detail == r"Folder not found: D:\Scores"

    waiting = output_status.files_status(r"D:\Scores", FileOutputStatus())
    assert (waiting.state, waiting.enabled) == (SENDING, True)

    files = FileOutputStatus(folder=r"D:\Scores", files=4, last_write_at=12.0)
    ok = output_status.files_status(r"D:\Scores", files)
    assert (ok.state, ok.detail, ok.last_activity_at) == (
        OK,
        r"Writing to D:\Scores · 4 files",
        12.0,
    )
    failing = FileOutputStatus(
        folder=r"D:\Scores",
        files=4,
        last_write_at=12.0,
        failing=("Home Score.txt", "Time.txt"),
        last_error="Home Score.txt: [Errno 13] Permission denied",
    )
    error = output_status.files_status(r"D:\Scores", failing)
    assert (error.state, error.detail) == (
        ERROR,
        "Can't write Home Score.txt and 1 more",
    )
    assert "Permission denied" in error.technical


def test_http_status():
    urls = ("http://192.168.1.20:18099", "http://localhost:18099")
    busy = output_status.http_status(None, 18099, (), HttpServerStats())
    assert (busy.state, busy.switchable) == (ERROR, False)
    assert busy.detail == "Not running: port 18099 is in use"
    assert "--port" in busy.hint

    idle = output_status.http_status(18099, 18099, urls, HttpServerStats())
    assert (idle.state, idle.detail) == (
        OK,
        "http://192.168.1.20:18099 · no requests yet",
    )
    busy_clients = output_status.http_status(
        18099,
        18099,
        urls,
        HttpServerStats(requests=50, last_request_at=3.0, recent_clients=3),
    )
    assert busy_clients.detail == "http://192.168.1.20:18099 · 3 clients"
    assert busy_clients.last_activity_at == 3.0
    one = output_status.http_status(
        18099, 18099, urls, HttpServerStats(requests=1, recent_clients=1)
    )
    assert one.detail.endswith("· 1 client")


def test_obs_status():
    assert output_status.obs_status(None, None, None, None).state == OFF
    connecting = output_status.obs_status(None, "localhost:4455", None, None)
    assert (connecting.state, connecting.detail) == (
        SENDING,
        "Connecting to localhost:4455…",
    )
    failed = output_status.obs_status(
        None,
        None,
        ErrorInfo(ConnectionRefusedError, "refused"),
        None,
        connect_target="localhost:4455",
    )
    assert (failed.state, failed.enabled) == (ERROR, False)
    assert failed.detail == "Not connected: Can't reach localhost:4455"
    assert "Connect OBS" in failed.hint

    ok = output_status.obs_status(
        "localhost:4455", None, None, WorkerStatus("OBS", sent=2, last_success_at=9.0)
    )
    assert (ok.state, ok.detail, ok.last_activity_at) == (
        OK,
        "Connected to localhost:4455",
        9.0,
    )
    # sent over an earlier connection
    reconnected = output_status.obs_status(
        "localhost:4455",
        None,
        None,
        WorkerStatus("OBS", last_success_at=9.0),
        connected_at=10.0,
    )
    assert reconnected.last_activity_at is None

    retrying = output_status.obs_status(
        "localhost:4455",
        None,
        None,
        WorkerStatus(
            "OBS", retrying=True, last_error=unreachable(OBSConnectionLost, "lost")
        ),
    )
    assert (retrying.state, retrying.detail) == (
        RETRYING,
        "Reconnecting to OBS at localhost:4455…",
    )
    no_sources = output_status.obs_status(
        "localhost:4455", None, None, WorkerStatus("OBS"), has_sources=False
    )
    assert no_sources.state == WARNING


def test_vmix_status():
    mapping = {"Time": "CLOCK.Text"}
    off = output_status.vmix_status(False, "localhost", "8088", "1", mapping, None)
    assert (off.state, off.enabled, off.detail) == (OFF, False, "Off")
    assert "localhost:8088" in off.hint

    empty = output_status.vmix_status(
        True, "localhost", "8088", "1", {"Time": ""}, None
    )
    assert (empty.state, empty.detail) == (WARNING, "No fields to send")

    waiting = output_status.vmix_status(
        True, "localhost", "8088", "1", mapping, WorkerStatus("vMix")
    )
    assert waiting.state == SENDING
    ok = output_status.vmix_status(
        True,
        "localhost",
        "8088",
        "1",
        mapping,
        WorkerStatus("vMix", sent=1, last_success_at=4.0),
    )
    assert (ok.state, ok.detail) == (OK, "Sending to localhost:8088, input 1")

    down = output_status.vmix_status(
        True,
        "192.168.1.40",
        "8088",
        "1",
        mapping,
        WorkerStatus(
            "vMix",
            sent=1,
            last_success_at=4.0,
            retrying=True,
            last_error=unreachable(requests.ConnectionError, REFUSED),
        ),
    )
    assert (down.state, down.detail) == (
        RETRYING,
        "Can't reach 192.168.1.40:8088 · retrying",
    )
    assert down.last_activity_at == 4.0  # the last value that did arrive
    assert "10061" in down.technical


def test_uno_status_needs_a_url():
    placeholder = "https://app.overlays.uno/apiv2/controlapps/.../api"
    status = output_status.uno_status(True, placeholder, {"Time": "SetMatchTime"}, None)
    assert (status.state, status.detail) == (WARNING, "Enter your UNO API URL")
    assert output_status.uno_status(False, UNO_URL, {}, None).state == OFF


def test_api_status():
    assert output_status.api_status(False, "", "POST", "JSON (Full)", None).state == OFF
    assert output_status.api_status(True, "", "POST", "JSON (Full)", None).detail == (
        "Enter a URL"
    )
    invalid = output_status.api_status(True, "localhost:8091", "POST", "XML", None)
    assert invalid.detail == "The URL isn't valid"
    ok = output_status.api_status(
        True,
        "http://192.168.1.10:8091/scores",
        "POST",
        "JSON (Full)",
        WorkerStatus("Output API", sent=1, last_success_at=1.0),
    )
    assert (ok.state, ok.detail) == (OK, "POST JSON (Full) to 192.168.1.10:8091")
    get = output_status.api_status(
        True,
        "http://192.168.1.10:8091/scores",
        "GET",
        "XML",
        WorkerStatus("Output API", sent=1, last_success_at=1.0),
    )
    assert get.detail == "GET to 192.168.1.10:8091"


# --- texts ------------------------------------------------------------------------


def test_ages():
    assert age_text(0.4) == "just now"
    assert age_text(3) == "3 s ago"
    assert age_text(125) == "2 min ago"
    assert age_text(7200) == "2 h ago"


def test_tooltip_and_accessible_text():
    status = DestinationStatus(
        VMIX,
        RETRYING,
        "Can't reach 192.168.1.40:8088 · retrying",
        enabled=True,
        hint="Check that vMix is running.",
        last_activity_at=10.0,
        technical="ConnectionError: refused",
    )
    tooltip = status_tooltip(status, now=13.0)
    assert tooltip.splitlines() == [
        "vMix: ▲ retrying",
        "Can't reach 192.168.1.40:8088 · retrying",
        "Check that vMix is running.",
        "Last sent 3 s ago",
        "Details: ConnectionError: refused",
    ]
    # the state in words too: never by colour alone
    assert accessible_text(status) == (
        "vMix, on, retrying, Can't reach 192.168.1.40:8088 · retrying"
    )
    http = DestinationStatus(HTTP, OK, "http://x:1", enabled=True, switchable=False)
    assert accessible_text(http) == "HTTP server, working, http://x:1"


def test_every_state_has_a_distinct_glyph_shape():
    shapes = {
        state: output_status.STATE_SHAPES[state]
        for state in (OFF, SENDING, OK, WARNING, ERROR)
    }
    assert len(set(shapes.values())) == len(shapes)
    assert set(output_status.STATE_GLYPHS) == set(output_status.STATES)


def test_destination_names():
    assert [
        output_status.destination_name(key) for key in output_status.DESTINATIONS
    ] == [
        "Text files",
        "HTTP server",
        "OBS",
        "vMix",
        "UNO",
        "HTTP API",
        "TCP / UDP",
        "Team Performance",
    ]
    assert output_status.short_name(FILES) == "Files"
    assert output_status.short_name(output_status.TCP) == "TCP"
    assert all(
        output_status.destination_description(key) for key in output_status.DESTINATIONS
    )
