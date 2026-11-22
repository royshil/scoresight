"""vMix API+ against a local Web API with several independent title inputs."""

import threading
import time
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import pytest

from output_worker import OutputError
from storage import store_data
from vmix_output import VMixAPI
from vmix_plus_output import VMixPlusAPI, title_fields


class FakeVmix:
    def __init__(self):
        self.inputs = {
            "scoreboard-guid": {"HOMESCORE.Text": "", "TIME.Text": ""},
            "halftime-guid": {"HOMESCORE.Text": ""},
            "timeout-guid": {"HOMESCORE.Text": "", "TIME.Text": ""},
        }
        self.calls = []
        self.fail = set()
        self.override_xml = None
        self.disconnect_sends = False
        self.discovery_started = threading.Event()
        self.release_discovery = threading.Event()
        self.release_discovery.set()
        self.lock = threading.Lock()
        state = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                query = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
                if query.get("Function") == ["SetText"]:
                    ref, name, value = (
                        query[k][0] for k in ("Input", "SelectedName", "Value")
                    )
                    with state.lock:
                        if state.disconnect_sends:
                            self.close_connection = True
                            return
                        state.calls.append((ref, name, value))
                        success = (
                            ref in state.inputs
                            and name in state.inputs[ref]
                            and (ref, name) not in state.fail
                        )
                        if success:
                            state.inputs[ref][name] = value
                    self.respond(
                        200 if success else 500,
                        "OK" if success else "Unknown title field",
                    )
                else:
                    # Capture before the delay, like an old response arriving
                    # after the operator changes connections or stops output.
                    xml = state.xml()
                    state.discovery_started.set()
                    state.release_discovery.wait(3)
                    self.respond(200, xml)

            def respond(self, status, text):
                body = text.encode()
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = str(self.server.server_port)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def xml(self):
        with self.lock:
            if self.override_xml is not None:
                return self.override_xml
            root = ET.Element("vmix")
            inputs = ET.SubElement(root, "inputs")
            for i, (ref, fields) in enumerate(self.inputs.items(), 1):
                node = ET.SubElement(
                    inputs, "input", key=ref, number=str(i), type="GT", title=ref
                )
                for name, value in fields.items():
                    ET.SubElement(node, "text", name=name).text = value
            return ET.tostring(root, encoding="unicode")

    def close(self):
        self.release_discovery.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(3)


@pytest.fixture
def vmix_servers():
    servers = []

    def make():
        server = FakeVmix()
        servers.append(server)
        return server

    yield make
    for server in servers:
        server.close()


@pytest.fixture
def plus(memory_storage, vmix_servers):
    server = vmix_servers()
    output = VMixPlusAPI(
        "127.0.0.1", server.port, {"Home Score": "HOMESCORE.Text", "Time": "TIME.Text"}
    )
    yield output, server
    server.release_discovery.set()
    output.close()


def flush(output):
    assert output._discovery.wait_idle(5)
    assert output._worker.wait_idle(5)


def test_every_matching_title_receives_values(plus, make_result):
    output, server = plus
    output.start()
    output.update_vmix([make_result("Home Score", "5"), make_result("Time", "12:34")])
    flush(output)
    assert len(server.calls) == 5
    assert all(fields["HOMESCORE.Text"] == "5" for fields in server.inputs.values())
    assert server.inputs["scoreboard-guid"]["TIME.Text"] == "12:34"
    assert server.inputs["timeout-guid"]["TIME.Text"] == "12:34"
    assert {ref for ref, _, _ in server.calls} == set(server.inputs)


def test_new_title_gets_last_good_values_without_an_ocr_change(plus, make_result):
    output, server = plus
    output.start()
    output.update_vmix([make_result("Home Score", "5")])
    flush(output)
    with server.lock:
        server.calls.clear()
        server.inputs["new-title-guid"] = {"HOMESCORE.Text": ""}
    output.refresh_fields()
    flush(output)
    assert server.calls == [("new-title-guid", "HOMESCORE.Text", "5")]
    output.refresh_fields()
    flush(output)
    assert len(server.calls) == 1


def test_guid_routing_survives_reordering_and_removal(plus, make_result):
    output, server = plus
    output.start()
    flush(output)
    with server.lock:
        server.inputs = {
            "timeout-guid": server.inputs["timeout-guid"],
            "scoreboard-guid": server.inputs["scoreboard-guid"],
        }
    output.refresh_fields()
    flush(output)
    output.update_vmix([make_result("Home Score", "7")])
    flush(output)
    assert {ref for ref, _, _ in server.calls} == {"scoreboard-guid", "timeout-guid"}


def test_one_bad_title_does_not_block_other_titles(plus, make_result):
    output, server = plus
    server.fail.add(("scoreboard-guid", "HOMESCORE.Text"))
    output.start()
    output.update_vmix([make_result("Home Score", "8")])
    flush(output)
    assert output.status().failing_keys == 1
    assert output.status().ok_keys == 2
    assert server.inputs["halftime-guid"]["HOMESCORE.Text"] == "8"
    assert server.inputs["timeout-guid"]["HOMESCORE.Text"] == "8"
    server.fail.clear()
    output.update_vmix([make_result("Home Score", "9")])
    flush(output)
    assert output.status().failing_keys == 0
    assert all(fields["HOMESCORE.Text"] == "9" for fields in server.inputs.values())


def test_unchanged_failed_and_cleared_values(plus, make_result):
    output, server = plus
    output.start()
    output.update_vmix([make_result("Home Score", "5")])
    flush(output)
    count = len(server.calls)
    for state in ("SameNoChange", "Empty", "FailedFilter"):
        output.update_vmix([make_result("Home Score", "bad", state)])
    flush(output)
    assert len(server.calls) == count
    output.update_vmix(
        [make_result("Home Score", "5", "SameNoChange")],
        resend_unchanged={"Home Score"},
    )
    flush(output)
    assert len(server.calls) == count + 3
    output.update_vmix([make_result("Home Score", "")])
    flush(output)
    assert all(fields["HOMESCORE.Text"] == "" for fields in server.inputs.values())


def test_mapping_change_uses_latest_values_and_can_be_disabled(plus, make_result):
    output, server = plus
    output.start()
    flush(output)
    output.set_field_mapping({"Home Score": ""})
    output.update_vmix([make_result("Home Score", "6", "SameNoChange")])
    flush(output)
    assert server.calls == []
    output.set_field_mapping({"Home Score": "HOMESCORE.Text"})
    flush(output)
    assert len(server.calls) == 3
    assert all(value == "6" for _, _, value in server.calls)


def test_stopped_output_does_not_send_and_restart_backfills(plus, make_result):
    output, server = plus
    output.update_vmix([make_result("Home Score", "5", "SameNoChange")])
    output.start()
    flush(output)
    assert len(server.calls) == 3
    output.stop()
    output.update_vmix([make_result("Home Score", "7")])
    flush(output)
    assert len(server.calls) == 3
    output.start()
    flush(output)
    assert len(server.calls) == 6
    assert all(fields["HOMESCORE.Text"] == "7" for fields in server.inputs.values())


def test_discovery_does_not_block_and_old_connection_is_discarded(
    plus, vmix_servers, make_result
):
    output, old = plus
    old.release_discovery.clear()
    output.update_vmix([make_result("Home Score", "5")])
    start = time.monotonic()
    output.start()
    assert time.monotonic() - start < 0.2
    assert old.discovery_started.wait(3)
    new = vmix_servers()
    new.inputs = {"new-guid": {"HOMESCORE.Text": ""}}
    output.set_connection("127.0.0.1", new.port)
    old.release_discovery.set()
    flush(output)
    assert old.calls == []
    assert new.calls == [("new-guid", "HOMESCORE.Text", "5")]
    assert output.fields() == {"HOMESCORE.Text": ("new-guid",)}


def test_stop_during_discovery_does_not_send(plus, make_result):
    output, server = plus
    server.release_discovery.clear()
    output.update_vmix([make_result("Home Score", "5")])
    output.start()
    assert server.discovery_started.wait(3)
    output.stop()
    server.release_discovery.set()
    flush(output)
    assert server.calls == []
    assert output.fields() == {}


def test_invalid_xml_and_recovery(plus):
    output, server = plus
    server.override_xml = "<html>Login</html>"
    output.refresh_fields()
    flush(output)
    assert output.discovery_status().failing_keys == 1
    assert output.fields() == {}
    server.override_xml = None
    output.refresh_fields()
    flush(output)
    assert output.discovery_status().failing_keys == 0
    assert "HOMESCORE.Text" in output.fields()


def test_automatic_refresh_is_throttled_and_off_means_no_polling(plus, monkeypatch):
    output, server = plus
    requested = []
    monkeypatch.setattr(output, "refresh_fields", lambda: requested.append(True))
    output.refresh(now=100)
    assert requested == []
    output.running = True
    output._refresh_at = 100
    output.refresh(now=104)
    assert requested == []
    output.refresh(now=105)
    assert requested == [True]


def test_settings_are_independent_from_single_input_vmix(plus):
    output, _ = plus
    legacy = VMixAPI("localhost", "8088", "1", {})
    try:
        store_data("scoresight.json", "vmix_send_same", True)
        assert legacy.update_same is True
        assert output.update_same is False
        store_data("scoresight.json", "vmix_plus_send_same", True)
        assert output.update_same is True
    finally:
        legacy.close()


def test_field_parser_deduplicates_and_preserves_exact_names():
    assert title_fields(
        '<vmix><inputs><input key="guid" number="1"><text name="Home Score.Text"/><text name="Home Score.Text"/></input><input number="2"><text name="Home Score.Text"/></input><input key="camera"/></inputs></vmix>'
    ) == {"Home Score.Text": ("guid", "2")}


@pytest.mark.parametrize("xml", ["", "<vmix>", "<html/>", "<vmix/>"])
def test_field_parser_rejects_non_vmix_xml(xml):
    with pytest.raises(OutputError):
        title_fields(xml)


def test_unreachable_receiver_recovers_with_latest_values(plus, make_result):
    output, server = plus
    server.disconnect_sends = True
    output.start()
    output.update_vmix([make_result("Home Score", "1")])
    assert output._discovery.wait_idle(5)
    deadline = time.monotonic() + 3
    while not output.status().retrying and time.monotonic() < deadline:
        time.sleep(0.01)
    assert output.status().retrying
    output.update_vmix([make_result("Home Score", "2")])
    output.update_vmix([make_result("Home Score", "3")])
    server.disconnect_sends = False
    flush(output)
    assert all(fields["HOMESCORE.Text"] == "3" for fields in server.inputs.values())
    assert not output.status().retrying


def test_encodes_names_and_values_without_changing_text(plus, make_result):
    output, server = plus
    server.inputs = {"guid & one": {"Home & Away.Text": ""}}
    output.set_field_mapping({"Home Score": "Home & Away.Text"})
    output.start()
    output.update_vmix([make_result("Home Score", "A & B + 5:58 / café")])
    flush(output)
    assert server.calls == [("guid & one", "Home & Away.Text", "A & B + 5:58 / café")]


def test_discovery_identifies_the_wrong_tcp_api_port(plus, monkeypatch):
    import requests
    from vmix_output import VMixTCPPortError

    output, _ = plus

    def wrong_port(*args, **kwargs):
        raise requests.ConnectionError("BadStatusLine('VERSION OK 28')")

    monkeypatch.setattr(output._discovery_session, "get", wrong_port)
    with pytest.raises(VMixTCPPortError, match="Web Controller port"):
        output._discover(None, (output._epoch, output.host, output.port))
