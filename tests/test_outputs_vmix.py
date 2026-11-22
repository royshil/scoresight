import logging
import socket
import threading
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
import requests

import storage
from output_worker import HTTP_TIMEOUT
from storage import fetch_data, store_data
from vmix_output import VMixAPI

SETTINGS = "scoresight.json"


class FakeResponse:
    def __init__(self, status_code=200, text="Function completed successfully."):
        self.status_code = status_code
        self.text = text
        self.headers = {}


class FakeSession:
    def __init__(self, status_code=200, delay=0.0, error=None):
        self.status_code = status_code
        self.delay = delay
        self.error = error
        self.calls = []
        self.lock = threading.Lock()

    def _record(self, method, url, **kwargs):
        with self.lock:
            self.calls.append((method, url, kwargs))
        if self.delay:
            time.sleep(self.delay)
        if self.error is not None:
            raise self.error
        return FakeResponse(self.status_code)

    def get(self, url, **kwargs):
        return self._record("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self._record("POST", url, **kwargs)

    def put(self, url, **kwargs):
        return self._record("PUT", url, **kwargs)

    def sent(self):
        """[(SelectedName, Value)] of the SetText calls, in order."""
        result = []
        for _, url, _ in self.calls:
            query = parse_qs(urlsplit(url).query)
            result.append((query["SelectedName"][0], query["Value"][0]))
        return result


@pytest.fixture
def make_vmix():
    created = []

    def _make(
        host="localhost", port="8088", input_number="1", mapping=None, session=None
    ):
        api = VMixAPI(host, port, input_number, mapping or {})
        api._session = session or FakeSession()
        created.append(api)
        return api

    yield _make
    for api in created:
        api.close()


def flush(api):
    assert api._worker.wait_idle(10)


def test_sends_set_text_with_a_timeout_and_no_body(make_vmix, make_result):
    api = make_vmix(host="10.0.0.5", input_number="3", mapping={"Time": "CLOCK.Text"})
    api.start()
    api.update_vmix([make_result("Time", "23:17", "Success")])
    flush(api)

    [(method, url, kwargs)] = api._session.calls
    assert method == "GET"
    parts = urlsplit(url)
    assert (parts.scheme, parts.netloc, parts.path) == (
        "http",
        "10.0.0.5:8088",
        "/api/",
    )
    assert parse_qs(parts.query) == {
        "Function": ["SetText"],
        "Input": ["3"],
        "SelectedName": ["CLOCK.Text"],
        "Value": ["23:17"],
    }
    assert kwargs == {"timeout": HTTP_TIMEOUT}  # no "data=" body any more


def test_spaces_are_sent_as_percent_20(make_vmix, make_result):
    # urlencode() sent spaces as "+", which vMix may show as a literal "+"
    api = make_vmix(mapping={"Home Team": "Home Team Name.Text"})
    api.start()
    api.update_vmix([make_result("Home Team", "Red Sox + Co", "Success")])
    flush(api)
    [(_, url, _)] = api._session.calls
    assert urlsplit(url).query == (
        "Function=SetText&Input=1&SelectedName=Home%20Team%20Name.Text"
        "&Value=Red%20Sox%20%2B%20Co"
    )
    assert api._session.sent() == [("Home Team Name.Text", "Red Sox + Co")]


def test_only_new_good_values_are_sent(make_vmix, make_result):
    mapping = {"Home Score": "Home.Text", "Away Score": "Away.Text", "Time": "T.Text"}
    api = make_vmix(mapping=mapping)
    api.start()
    results = [
        make_result("Home Score", "12", "Success"),
        make_result("Away Score", "7", "SameNoChange"),
        make_result("Time", "SIM", "FailedFilter"),
        make_result("Period", "2", "Success"),  # not mapped
    ]
    api.update_vmix(results)
    flush(api)
    assert api._session.sent() == [("Home.Text", "12")]

    api.set_update_same(True)
    api.update_vmix(results)
    flush(api)
    assert api._session.sent()[1:] == [("Home.Text", "12"), ("Away.Text", "7")]


def test_unchanged_values_are_sent_on_request(make_vmix, make_result):
    # after the outputs were paused, a value that changed meanwhile is an
    # unchanged reading: the main window asks for it, for the boxes named
    api = make_vmix(
        mapping={"Home Score": "Home.Text", "Away Score": "Away.Text", "Time": "T.Text"}
    )
    api.start()
    results = [
        make_result("Home Score", "3", "SameNoChange"),
        make_result("Away Score", "7", "SameNoChange"),
        make_result("Time", "SIM", "FailedFilter"),  # never sent
    ]
    api.update_vmix(results, resend_unchanged={"Away Score", "Time"})
    api.update_vmix(results)
    flush(api)
    assert api._session.sent() == [("Away.Text", "7")]


def test_nothing_is_sent_unless_running(make_vmix, make_result):
    api = make_vmix(mapping={"Time": "T.Text"})
    api.update_vmix([make_result("Time", "1:00", "Success")])
    api.start()
    api.stop()
    api.update_vmix([make_result("Time", "1:00", "Success")])
    assert api._worker.pending() == {}
    assert api._session.calls == []


def test_update_never_blocks_on_an_unresponsive_vmix(make_vmix, make_result):
    # e.g. the vMix PC was switched off: each request waits for its timeout
    session = FakeSession(delay=0.25)
    api = make_vmix(mapping={"Time": "T.Text", "Home Score": "H.Text"}, session=session)
    api.start()

    start = time.monotonic()
    for second in range(60, 0, -1):
        api.update_vmix(
            [
                make_result("Time", f"0:{second:02}", "Success"),
                make_result("Home Score", str(second), "Success"),
            ]
        )
    assert time.monotonic() - start < 1.0  # blocking would take 15 s+

    flush(api)
    # no backlog: the batch in flight, then only the latest value per field. The
    # order of the fields isn't fixed: the worker may take a batch between the
    # two fields of one update.
    assert dict(session.sent()) == {"T.Text": "0:01", "H.Text": "1"}
    assert len(session.sent()) <= 10  # of 120 submitted (typically 4)


def test_set_connection_keeps_mapping_and_running_state(make_vmix, make_result):
    api = make_vmix(mapping={"Time": "T.Text"})
    api.start()
    api.set_connection("192.168.1.50", "8088", "2")
    assert api.running
    assert api.field_mapping == {"Time": "T.Text"}

    api.update_vmix([make_result("Time", "1:00", "Success")])
    flush(api)
    [(_, url, _)] = api._session.calls
    assert url.startswith("http://192.168.1.50:8088/api/?")
    assert parse_qs(urlsplit(url).query)["Input"] == ["2"]


def test_error_status_is_logged(make_vmix, make_result, caplog):
    api = make_vmix(mapping={"Time": "T.Text"}, session=FakeSession(status_code=500))
    api.start()
    with caplog.at_level(logging.ERROR):
        api.update_vmix([make_result("Time", "1:00", "Success")])
        flush(api)
    assert "returned HTTP 500" in caplog.text


@pytest.fixture
def fake_vmix_tcp_api():
    """A server that behaves like vMix's TCP API on port 8099: it greets every
    connection with "VERSION OK ..." instead of answering HTTP."""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(5)
    server.settimeout(0.2)
    stop = threading.Event()

    def serve():
        while not stop.is_set():
            try:
                conn, _ = server.accept()
            except (TimeoutError, OSError):
                continue
            with conn:
                conn.settimeout(5)
                try:
                    conn.sendall(b"VERSION OK 26.0.0.45\r\n")
                    while conn.recv(4096):  # until the client hangs up
                        pass
                except OSError:
                    pass

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    yield server.getsockname()[1]
    stop.set()
    thread.join(2)
    server.close()


def test_tcp_api_port_gets_a_clear_hint(
    make_vmix, make_result, caplog, fake_vmix_tcp_api
):
    # issue #55: BadStatusLine('VERSION OK 26.0.0.45') on port 8099
    with requests.Session() as session:
        api = make_vmix(
            host="127.0.0.1",
            port=str(fake_vmix_tcp_api),
            mapping={"Time": "CLOCK.Text"},
            session=session,
        )
        api.start()
        with caplog.at_level(logging.ERROR):
            api.update_vmix([make_result("Time", "23:17", "Success")])
            deadline = time.monotonic() + 10
            while "VERSION OK" not in caplog.text and time.monotonic() < deadline:
                time.sleep(0.05)
        api.stop()
        flush(api)
    assert "vMix TCP API" in caplog.text
    assert "Web Controller" in caplog.text
    assert "8088" in caplog.text


def wait_for(condition, timeout=10.0):
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.02)


def vmix_destination(api):
    import output_status

    return output_status.vmix_status(
        api.running,
        api.host,
        api.port,
        api.input_number,
        api.field_mapping,
        api.status(),
    )


def test_status_on_the_tcp_api_port(make_vmix, make_result, fake_vmix_tcp_api):
    # issue #55, as the window shows it
    with requests.Session() as session:
        api = make_vmix(
            host="127.0.0.1",
            port=str(fake_vmix_tcp_api),
            mapping={"Time": "CLOCK.Text"},
            session=session,
        )
        api.start()
        api.update_vmix([make_result("Time", "23:17", "Success")])
        wait_for(lambda: api.status().last_error is not None)
        destination = vmix_destination(api)
        api.stop()
        flush(api)
    assert destination.state == "error"
    assert destination.detail == (
        f"Port {fake_vmix_tcp_api} is vMix's TCP API: use 8088"
    )
    # stopping turns it off and forgets the error
    assert api.status().last_error is None
    assert vmix_destination(api).state == "off"


@pytest.fixture
def fake_vmix_web_api():
    """A local HTTP server answering like vMix's Web API, with a settable
    status (401 when vMix requires a login)."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    state = {"status": 200, "requests": 0}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            state["requests"] += 1
            body = b"Function completed successfully."
            if state["status"] == 401:
                body = b"Unauthorized"
            self.send_response(state["status"])
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state["port"] = server.server_address[1]
    yield state
    server.shutdown()
    server.server_close()


def test_status_ok_then_login_required(make_vmix, make_result, fake_vmix_web_api):
    with requests.Session() as session:
        api = make_vmix(
            host="127.0.0.1",
            port=str(fake_vmix_web_api["port"]),
            mapping={"Time": "CLOCK.Text"},
            session=session,
        )
        api.start()
        assert vmix_destination(api).state == "sending"  # nothing sent yet
        api.update_vmix([make_result("Time", "1:00", "Success")])
        flush(api)
        ok = vmix_destination(api)
        assert (ok.state, ok.last_activity_at is not None) == ("ok", True)
        assert ok.detail == (
            f"Sending to 127.0.0.1:{fake_vmix_web_api['port']}, input 1"
        )

        fake_vmix_web_api["status"] = 401  # a Web Controller password was set
        api.update_vmix([make_result("Time", "0:59", "Success")])
        flush(api)
        error = vmix_destination(api)
        assert (error.state, error.detail) == (
            "error",
            "HTTP 401: vMix asks for a login",
        )
        assert "without login" in error.hint

        fake_vmix_web_api["status"] = 200  # the API page is allowed again
        api.update_vmix([make_result("Time", "0:58", "Success")])
        flush(api)
        assert vmix_destination(api).state == "ok"


def test_close_unsubscribes_from_settings(make_vmix):
    api = make_vmix()
    store_data(SETTINGS, "vmix_send_same", True)
    assert api.update_same is True

    api.close()
    store_data(SETTINGS, "vmix_send_same", False)
    assert api.update_same is True
    assert storage.data_subscribers.get(SETTINGS, {}).get("vmix_send_same") is None


# --- the VMix tab ----------------------------------------------------------


@pytest.fixture
def vmix_ui(qapp, qtbot):
    from PySide6.QtWidgets import QMainWindow
    from ui_mainwindow import Ui_MainWindow

    window = QMainWindow()
    qtbot.addWidget(window)
    ui = Ui_MainWindow()
    ui.setupUi(window)
    yield ui


@pytest.fixture
def make_handler(vmix_ui):
    from vmix_ui_handler import VMixUIHanlder

    handlers = []

    def _make():
        handler = VMixUIHanlder(vmix_ui)
        handler.vmixUpdater._session = FakeSession()
        handler.vmixUpdater._discovery_session = SimpleNamespace(
            get=lambda *a, **kw: FakeResponse(text="<vmix><inputs/></vmix>")
        )
        handlers.append(handler)
        return handler

    yield _make
    for handler in handlers:
        handler.vmixUpdater.close()


def edit(line_edit, text):
    line_edit.setText(text)
    line_edit.editingFinished.emit()


@pytest.mark.qt
def test_default_port_is_the_web_api_port(make_handler, vmix_ui):
    handler = make_handler()
    assert vmix_ui.lineEdit_vmixPort.text() == "8088"
    assert handler.vmixUpdater.port == "8088"


@pytest.mark.qt
def test_stored_tcp_api_port_is_migrated_once(make_handler, vmix_ui, caplog):
    store_data(SETTINGS, "vmix_port", "8099")
    with caplog.at_level(logging.INFO):
        handler = make_handler()
    assert vmix_ui.lineEdit_vmixPort.text() == "8088"
    assert handler.vmixUpdater.port == "8088"
    assert fetch_data(SETTINGS, "vmix_port") == "8088"
    assert "vMix port changed from 8099" in caplog.text

    # a port the user sets afterwards is respected
    store_data(SETTINGS, "vmix_port", "8099")
    handler.vmixUpdater.close()
    handler = make_handler()
    assert vmix_ui.lineEdit_vmixPort.text() == "8099"


@pytest.mark.qt
def test_other_stored_ports_are_kept(make_handler, vmix_ui):
    store_data(SETTINGS, "vmix_port", "9000")
    make_handler()
    assert vmix_ui.lineEdit_vmixPort.text() == "9000"
    assert fetch_data(SETTINGS, "vmix_port") == "9000"


@pytest.mark.qt
def test_default_mapping_shown_in_the_table_is_applied(
    make_handler, vmix_ui, make_target, make_result
):
    # fresh install: the table shows box name -> box name, which used to never
    # reach the updater ("Field mapping is not set")
    handler = make_handler()
    handler.updatevMixTable([make_target("Home Score"), make_target("Time")])
    assert handler.vmixUpdater.field_mapping == {
        "Home Score": "Home Score",
        "Time": "Time",
    }
    assert fetch_data(SETTINGS, "vmix_mapping") is None  # not stored

    vmix_ui.pushButton_startvmix.setChecked(True)
    handler.vmixUpdater.update_vmix([make_result("Time", "1:00", "Success")])
    assert handler.vmixUpdater._worker.wait_idle(10)
    assert handler.vmixUpdater._session.sent() == [("Time", "1:00")]


@pytest.mark.qt
def test_table_uses_stored_mapping_and_follows_the_boxes(
    make_handler, vmix_ui, make_target
):
    store_data(SETTINGS, "vmix_mapping", {"Time": "CLOCK.Text", "Gone": "X.Text"})
    handler = make_handler()
    handler.updatevMixTable([make_target("A"), make_target("Time"), make_target("B")])
    handler.updatevMixTable([make_target("Time"), make_target("C")])

    model = vmix_ui.tableView_vmixMapping.model()
    rows = [
        (model.item(i, 0).text(), model.item(i, 1).text())
        for i in range(model.rowCount())
    ]
    assert rows == [("Time", "CLOCK.Text"), ("C", "C")]
    assert handler.vmixUpdater.field_mapping == {"Time": "CLOCK.Text", "C": "C"}


@pytest.mark.qt
def test_editing_a_mapping_cell_stores_and_applies_it(
    make_handler, vmix_ui, make_target
):
    handler = make_handler()
    handler.updatevMixTable([make_target("Time")])
    vmix_ui.tableView_vmixMapping.model().item(0, 1).setText("CLOCK.Text")
    assert fetch_data(SETTINGS, "vmix_mapping") == {"Time": "CLOCK.Text"}
    assert handler.vmixUpdater.field_mapping == {"Time": "CLOCK.Text"}


@pytest.mark.qt
def test_connection_edit_keeps_mapping_and_running_state(
    make_handler, vmix_ui, make_target
):
    handler = make_handler()
    updater = handler.vmixUpdater
    handler.updatevMixTable([make_target("Time")])
    vmix_ui.pushButton_startvmix.setChecked(True)
    assert updater.running

    edit(vmix_ui.lineEdit_vmixHost, " 192.168.1.50 ")
    edit(vmix_ui.inputLineEdit_vmix, "2")

    assert handler.vmixUpdater is updater
    assert updater.running
    assert vmix_ui.pushButton_startvmix.isChecked()
    assert updater.field_mapping == {"Time": "Time"}
    assert (updater.host, updater.port, updater.input_number) == (
        "192.168.1.50",
        "8088",
        "2",
    )
    assert fetch_data(SETTINGS, "vmix_host") == "192.168.1.50"
    assert fetch_data(SETTINGS, "vmix_input") == "2"


@pytest.mark.qt
def test_typing_alone_does_not_reconfigure(make_handler, vmix_ui):
    # retranslateUi() and every keystroke call setText/textChanged; only a
    # finished edit applies and stores the connection
    handler = make_handler()
    vmix_ui.lineEdit_vmixPort.setText("80")
    assert handler.vmixUpdater.port == "8088"
    assert fetch_data(SETTINGS, "vmix_port") is None  # nothing stored


@pytest.mark.qt
def test_restore_ui_state(make_handler, vmix_ui):
    handler = make_handler()
    edit(vmix_ui.lineEdit_vmixHost, "vmix-pc")
    vmix_ui.pushButton_startvmix.setChecked(True)
    # what retranslateUi() does
    vmix_ui.lineEdit_vmixHost.setText("localhost")
    vmix_ui.lineEdit_vmixPort.setText("8099")
    vmix_ui.pushButton_startvmix.setText("Start")

    handler.restoreUiState()
    assert vmix_ui.lineEdit_vmixHost.text() == "vmix-pc"
    assert vmix_ui.lineEdit_vmixPort.text() == "8088"
    assert "Stop" in vmix_ui.pushButton_startvmix.text()
    assert handler.vmixUpdater.running


@pytest.mark.qt
def test_handler_does_not_leak_settings_subscriptions(make_handler, vmix_ui):
    handler = make_handler()
    for host in ("a", "b", "c"):
        edit(vmix_ui.lineEdit_vmixHost, host)
    callbacks = storage.data_subscribers[SETTINGS]["vmix_send_same"]
    assert callbacks == [handler.vmixUpdater.set_update_same]
