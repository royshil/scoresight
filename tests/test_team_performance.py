"""Timing device contracts, read over the same HTTP server as other outputs."""

import pytest
import requests

import http_server
from team_performance import TimingConfig, scoreboard_time, shot_clock_time


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("12:34", {"minute": 12, "second": 34}),
        (" 00:00 ", {"minute": 0, "second": 0}),
        ("25:00", {"minute": 25, "second": 0}),
        ("120:59.9", {"minute": 120, "second": 59}),
        ("0:09.8", {"minute": 0, "second": 9}),
        ("23:4", {"minute": 0, "second": 23}),
        ("9.9", {"minute": 0, "second": 9}),
        ("9,9", {"minute": 0, "second": 9}),
        ("0", {"minute": 0, "second": 0}),
    ],
)
def test_match_formats(raw, expected):
    assert scoreboard_time(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["", "SIM", "nan", "inf", "-1", "1:60", "60", "1:2:3", "1e1", "1000:00", "9..9"],
)
def test_invalid_match_formats(raw):
    with pytest.raises(ValueError):
        scoreboard_time(raw)


@pytest.mark.parametrize(
    "raw,value",
    [
        ("25", 25),
        ("14", 14),
        ("0", 0),
        ("99", 99),
        ("9.8", 9.8),
        ("9,8", 9.8),
        ("9:8", 9.8),
    ],
)
def test_shot_clock_formats(raw, value):
    assert shot_clock_time(raw) == {"time": value}


@pytest.mark.parametrize("raw", ["", "NaN", "inf", "-1", "100", "99.1", "1:23", "1e1"])
def test_invalid_shot_clock_formats(raw):
    with pytest.raises(ValueError):
        shot_clock_time(raw)


@pytest.fixture(scope="module")
def timing_server():
    http_server.start_http_server(port=0)
    port = http_server.get_http_server_port()
    assert port
    yield f"http://127.0.0.1:{port}"
    http_server.stop_http_server()


@pytest.fixture
def client(timing_server):
    http_server.update_http_server([])
    http_server.configure_team_performance(TimingConfig(enabled=True))

    class Client:
        def get(self, path):
            return requests.get(timing_server + path, timeout=5)

    yield Client()
    http_server.configure_team_performance(TimingConfig())
    http_server.update_http_server([])


def publish(make_result, time="12:34", shot="25", state="Success"):
    http_server.update_http_server(
        [make_result("Time", time, state), make_result("Shot Clock", shot, state)]
    )


@pytest.mark.parametrize(
    "path,expected",
    [
        ("/timeclock/time-as-array", [{"minute": 12, "second": 34}]),
        ("/timeclock/time-as-object", {"minute": 12, "second": 34}),
        ("/time", {"time": 25}),
        ("/time-as-array", [{"time": 25}]),
    ],
)
def test_timing_contract(client, make_result, path, expected):
    publish(make_result)
    response = client.get(path)
    assert response.status_code == 200
    assert response.json() == expected
    assert "no-store" in response.headers["cache-control"]
    assert response.headers["content-type"].startswith("application/json")
    assert http_server.team_performance_last_request() is not None


@pytest.mark.parametrize(
    "path",
    [
        "/time",
        "/time-as-array",
        "/timeclock/time-as-array",
        "/timeclock/time-as-object",
    ],
)
def test_no_reading_is_unavailable(client, path):
    assert client.get(path).status_code == 503


def test_last_good_value_and_removed_field(client, make_result):
    publish(make_result)
    publish(make_result, time="SIM", shot="bad", state="FailedFilter")
    assert client.get("/time").json() == {"time": 25}
    assert client.get("/timeclock/time-as-array").json() == [
        {"minute": 12, "second": 34}
    ]
    http_server.update_http_server([])
    assert client.get("/time").status_code == 503
    assert client.get("/timeclock/time-as-array").status_code == 503


def test_clock_stops_resets_and_tenths(client, make_result):
    for time, shot, minute, second in [
        ("25:00", "25", 25, 0),
        ("24:59", "24", 24, 59),
        ("24:59", "24", 24, 59),
        ("10:00", "25", 10, 0),
        ("0:09.9", "9.9", 0, 9),
        ("0", "0", 0, 0),
    ]:
        publish(make_result, time, shot)
        assert client.get("/timeclock/time-as-object").json() == {
            "minute": minute,
            "second": second,
        }
        assert client.get("/time").json() == {"time": float(shot)}


def test_disabled_output_does_not_affect_other_endpoints(client, make_result):
    publish(make_result)
    http_server.configure_team_performance(TimingConfig())
    assert client.get("/time").status_code == 503
    assert client.get("/timeclock/time-as-array").status_code == 503
    assert client.get("/json?pivot&all").json() == {"Time": "12:34", "Shot Clock": "25"}


def test_custom_mapping_and_independent_clock_errors(client, make_result):
    http_server.configure_team_performance(TimingConfig(True, "Match", "Possession"))
    http_server.update_http_server(
        [make_result("Match", "09:08"), make_result("Possession", "nan")]
    )
    assert client.get("/timeclock/time-as-object").json() == {"minute": 9, "second": 8}
    assert client.get("/time").status_code == 503
    http_server.update_http_server(
        [make_result("Match", ""), make_result("Possession", "14")]
    )
    assert client.get("/timeclock/time-as-array").status_code == 503
    assert client.get("/time").json() == {"time": 14}
