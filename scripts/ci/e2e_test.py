"""End-to-end test: run the real ScoreSight app headless on a synthetic
scoreboard video and check that the readings reach the outputs.

    python scripts/ci/e2e_test.py -- python src/main.py
    python scripts/ci/e2e_test.py --engine tesseract -- python src/main.py
    python scripts/ci/e2e_test.py --json e2e.json -- dist/scoresight/scoresight.exe
    python scripts/ci/e2e_test.py -- dist/ScoreSight.app/Contents/MacOS/scoresight

--engine chooses the OCR engine: ppocr (the default) leaves the OCR model out
of the settings, as in a new setup, whose default is PP-OCR (automatic: the
accurate model while it keeps up, the fast one when it doesn't); tesseract
chooses the General Scoreboard model. Either way the app's log must show that
engine reading (a PP-OCR that couldn't load falls back to Tesseract, which
would otherwise pass unnoticed), and with ppocr the settings file must then
have PP-OCR (automatic) stored as the OCR model. Whether automatic switched to
the fast model is in the results' details.

What it does:
1. Renders a scoreboard video with the 7-segment digits of
   tests/synthetic_images.py (MJPG in an .avi file, which the OpenCV wheels can
   write and read on every OS): the home score goes 0 -> 1 -> 2 while the away
   score stays 3 and the clock counts down from 12:00, then the clock stops and
   the final state (2, 3, 11:51) holds for 8 s.
2. Writes the settings of the profile "e2e" in a throw-away settings folder:
   the video as the source (opened at startup), Home Score, Away Score and Time
   boxes, 10 detections per second, the .txt files, results.csv (appended rows)
   and results.xml in an output folder, and the outbound HTTP API pointed at a
   mock server that this script runs.
3. Starts the app (--profile e2e --port <free port>, offscreen) and polls GET
   /json until the server answers, until the first reading and until the final
   state is read. Every reading on the way must be one of the video's values
   (a rejected or empty reading is allowed, a wrong value isn't), and the home
   score must be seen going 0 -> 1 -> 2. It checks /csv and /xml, the files and
   what the mock API received the same way, and the browser overlays' live
   values: GET /overlay/state, and the Server-Sent Events of /events followed
   over one connection for the whole run.
4. Stops the app like a user would (SIGTERM; Ctrl+Break on Windows), requires
   exit code 0, and checks that the settings file still has the boxes.

On failure it prints the app's output and log files and exits with 1. --json
writes the timings and results; in GitHub Actions a table is added to the job
summary.

What the design accounts for:
- A File source (src/camera_thread.py) is read as fast as the capture loop runs
  (a frame every 30 ms at most, less often while OCR runs), not at the file's
  frame rate, and at the end of the file it seeks back to frame 0 and plays it
  again, forever. So the timeline is in frames, the final state is held long
  enough to be seen, and each output is checked over the whole run (every value
  must be valid, the full sequence and the final state must be seen) rather
  than only at the end.
- vMix isn't tested: the vMix output sends only after "Start vMix" is clicked,
  and that isn't saved (VMixAPI.running is False at every start).
- With Tesseract the boxes use the General Scoreboard model with autocrop on
  and no dilation, which reads every frame of this video correctly; PP-OCR
  ignores those Image cleanup settings and reads every frame correctly too.
  tests/test_ci_scripts.py checks both with the real OCR, so a model, engine or
  Tesseract change shows up there first.
"""

import argparse
import csv
import http.client
import http.server
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

import app_harness

REPO_ROOT = Path(__file__).resolve().parents[2]
PROFILE = "e2e"

# --- the synthetic scoreboard ---------------------------------------------------

FPS = 30
FRAME_WIDTH, FRAME_HEIGHT = 640, 360
BACKGROUND, FOREGROUND = 16, 235
DIGIT_HEIGHT = 80
# box name -> (x, y, width, height) in the frame
BOXES = {
    "Home Score": (40, 180, 150, 120),
    "Away Score": (470, 180, 150, 120),
    "Time": (150, 20, 340, 120),
}
# Each box's settings; the app fills in the rest (type, format, ...) with the
# defaults of these predefined boxes.
BOX_SETTINGS = {"autocrop": True, "dilate": 0}
OCR_MODEL_GENERAL_SCOREBOARD = 1  # TextDetector.OcrModelIndex.SCOREBOARD_GENERAL
# a new setup's OCR model (ocr_models.DEFAULT_MODEL), stored when its source opens
OCR_MODEL_PPOCR_DEFAULT = "ppocr:auto"
# the model PP-OCR (automatic) reads with first, and with which it is tested
OCR_MODEL_PPOCR_ACCURATE = "ppocr:small"
# logged when PP-OCR (automatic) switches to its fast model
PPOCR_AUTO_FAST_LOG_LINE = "PP-OCR automatic: reading with fast"
ENGINES = ("ppocr", "tesseract")
# what the app logs once the engine reads (src/ppocr_engine.py, src/tesseract.py)
ENGINE_LOG_LINES = {
    "ppocr": "PP-OCR: loaded PP-OCRv6_small_rec",
    "tesseract": "Setting OCR model to scoreboard_general",
}
# logged when PP-OCR couldn't load and Tesseract reads instead
PPOCR_FALLBACK_LOG_LINE = "reading the boxes with Tesseract"
BOXES_SCHEMA_VERSION = 4  # storage.BOXES_SCHEMA_VERSION
FINAL_HOLD_SECONDS = 8


@dataclass(frozen=True)
class State:
    """What the scoreboard shows."""

    home: str
    away: str
    time: str

    def values(self) -> dict[str, str]:
        return {"Home Score": self.home, "Away Score": self.away, "Time": self.time}


def _clock(seconds: int) -> str:
    return f"{seconds // 60}:{seconds % 60:02d}"


def build_timeline() -> list[tuple[State, int]]:
    """The video as (state, number of frames), in playing order."""
    timeline = []
    clock = 12 * 60
    for home in ("0", "1", "2"):
        for _ in range(3):
            timeline.append((State(home, "3", _clock(clock)), FPS))
            clock -= 1
    # the clock stops
    timeline.append((State("2", "3", _clock(clock)), FINAL_HOLD_SECONDS * FPS))
    return timeline


def allowed_values(timeline) -> dict[str, set[str]]:
    """Every value each box shows in the video."""
    allowed = {name: set() for name in BOXES}
    for state, _ in timeline:
        for name, value in state.values().items():
            allowed[name].add(value)
    return allowed


def _load_synthetic_images():
    path = REPO_ROOT / "tests" / "synthetic_images.py"
    spec = importlib.util.spec_from_file_location("synthetic_images", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def render_frame(state: State, synthetic_images=None) -> np.ndarray:
    """A BGR frame of the scoreboard: the scores right-aligned at the bottom,
    the clock centered at the top, light 7-segment digits on a dark board."""
    synthetic_images = synthetic_images or _load_synthetic_images()
    frame = np.full((FRAME_HEIGHT, FRAME_WIDTH), BACKGROUND, np.uint8)

    def digits(text):
        return synthetic_images.seven_segment(
            text, height=DIGIT_HEIGHT, fg=FOREGROUND, bg=BACKGROUND, pad=0
        )

    for name, text in (("Home Score", state.home), ("Away Score", state.away)):
        x, y, width, height = BOXES[name]
        image = digits(text)
        right = x + width - 20
        top = y + (height - image.shape[0]) // 2
        frame[top : top + image.shape[0], right - image.shape[1] : right] = image
    x, y, width, height = BOXES["Time"]
    image = digits(state.time)
    left = x + (width - image.shape[1]) // 2
    top = y + (height - image.shape[0]) // 2
    frame[top : top + image.shape[0], left : left + image.shape[1]] = image
    return cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)


def write_video(path: Path, timeline) -> int:
    """Write the timeline as an MJPG .avi file and check that it reads back.
    Returns the number of frames."""
    synthetic_images = _load_synthetic_images()
    writer = cv2.VideoWriter(
        str(path), cv2.VideoWriter_fourcc(*"MJPG"), FPS, (FRAME_WIDTH, FRAME_HEIGHT)
    )
    if not writer.isOpened():
        raise RuntimeError(f"OpenCV can't write MJPG video to {path}")
    frames = 0
    try:
        for state, count in timeline:
            frame = render_frame(state, synthetic_images)
            for _ in range(count):
                writer.write(frame)
            frames += count
    finally:
        writer.release()
    read_back = count_video_frames(path)
    if read_back != frames:
        raise RuntimeError(f"{path} has {read_back} readable frames, not {frames}")
    return frames


def count_video_frames(path: Path) -> int:
    capture = cv2.VideoCapture(str(path))
    try:
        frames = 0
        while True:
            ok, frame = capture.read()
            if not ok:
                return frames
            if frame.shape[:2] != (FRAME_HEIGHT, FRAME_WIDTH):
                raise RuntimeError(f"{path}: frame {frames} is {frame.shape}")
            frames += 1
    finally:
        capture.release()


# --- the app's settings ---------------------------------------------------------


def app_settings(
    video_path: Path, output_dir: Path, api_url: str, engine: str = "ppocr"
) -> dict:
    """The profile's settings file (keys as read by src/mainwindow.py and the
    output modules). engine "ppocr" leaves the OCR model out (a new setup's
    default); "tesseract" chooses General Scoreboard."""
    if engine not in ENGINES:
        raise ValueError(f"unknown engine {engine!r}")
    settings = {
        # opened by MainWindow.restoreSelectedSource after source discovery
        "source_selected": {"type": "File", "value": str(video_path)},
        "boxes": [
            {
                "name": name,
                "rect": {"x": x, "y": y, "width": width, "height": height},
                "settings": dict(BOX_SETTINGS),
                "mini_rects": [],
            }
            for name, (x, y, width, height) in BOXES.items()
        ],
        "boxes_schema_version": BOXES_SCHEMA_VERSION,
        "detection_cadence": 10,  # detections per second
        "update_on_change": True,
        # files: a .txt per box (overwritten), results.csv (a row appended per
        # change) and results.xml, written up to 10 times per second
        "output_folder": str(output_dir),
        "append_method": 0,
        "save_csv": True,
        "save_xml": True,
        "aggs_per_second": 10,
        # the outbound API: every detection cycle, POSTed as JSON (Full)
        "enable_out_api": True,
        "out_api_url": api_url,
        "out_api_method": "POST",
        "out_api_encoding": "JSON (Full)",
        # no requests to GitHub
        "disable_update_checks": True,
    }
    if engine == "tesseract":
        settings["ocr_model"] = OCR_MODEL_GENERAL_SCOREBOARD
    return settings


def settings_path(data_dir: Path) -> Path:
    return data_dir / f"scoresight-{PROFILE}.json"


# --- the mock API endpoint ----------------------------------------------------------


class MockReceiver:
    """A local HTTP server that stands in for the outbound API's endpoint and
    records every request."""

    def __init__(self):
        self.requests: list[tuple[float, str, str, bytes]] = []
        self._lock = threading.Lock()
        receiver = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def _record(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                with receiver._lock:
                    receiver.requests.append(
                        (time.perf_counter(), self.command, self.path, body)
                    )
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"ok")

            do_GET = do_POST = do_PUT = _record

            def log_message(self, format, *args):
                pass

        self.server = http.server.ThreadingHTTPServer(
            (app_harness.LOCALHOST, 0), Handler
        )
        self.server.daemon_threads = True
        self.thread = threading.Thread(
            target=self.server.serve_forever, name="mock-api", daemon=True
        )

    @property
    def url(self) -> str:
        return f"http://{app_harness.LOCALHOST}:{self.server.server_port}/scoresight"

    def start(self):
        self.thread.start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()

    def snapshot(self) -> list[tuple[float, str, str, bytes]]:
        with self._lock:
            return list(self.requests)


# --- what the outputs showed ----------------------------------------------------------

GOOD_STATES = ("Success", "SameNoChange")


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""


def collapse(values: list[str]) -> list[str]:
    """values without consecutive repeats."""
    return [v for i, v in enumerate(values) if i == 0 or v != values[i - 1]]


def contains_in_order(values: list[str], expected: list[str]) -> bool:
    """Whether expected is a subsequence of values."""
    it = iter(values)
    return all(any(v == e for v in it) for e in expected)


@dataclass
class OutputHistory:
    """The readings one output showed over time, as {box: [values]}, plus the
    invalid ones. A reading is valid if it is one of the video's values; a
    reading that isn't good (rejected, empty) only counts as transient."""

    name: str
    allowed: dict[str, set[str]]
    final: dict[str, str]
    values: dict[str, list[str]] = field(default_factory=dict)
    invalid: list[str] = field(default_factory=list)
    transient: int = 0
    final_seen_at: float | None = None
    samples: int = 0

    def add(self, readings: dict[str, tuple[str, str]], at: float | None = None):
        """readings: {box: (text, state)}."""
        self.samples += 1
        good = {}
        for box, (text, state) in readings.items():
            if box not in self.allowed:
                self.invalid.append(f"unexpected box {box!r}")
                continue
            if state not in GOOD_STATES:
                self.transient += 1
                continue
            if text not in self.allowed[box]:
                self.invalid.append(f"{box} = {text!r} ({state})")
                continue
            good[box] = text
            history = self.values.setdefault(box, [])
            if not history or history[-1] != text:
                history.append(text)
        if self.final_seen_at is None and good == self.final:
            self.final_seen_at = time.perf_counter() if at is None else at

    def sequence_seen(self, box: str, expected: list[str]) -> bool:
        return contains_in_order(collapse(self.values.get(box, [])), expected)

    def checks(self, home_sequence: list[str]) -> list[Check]:
        shown = {box: collapse(v) for box, v in self.values.items()}
        return [
            Check(
                f"{self.name}: only the video's values",
                not self.invalid,
                "; ".join(self.invalid[:10])
                + (
                    f" (+{len(self.invalid) - 10} more)"
                    if len(self.invalid) > 10
                    else ""
                ),
            ),
            Check(
                f"{self.name}: home score went {' -> '.join(home_sequence)}",
                self.sequence_seen("Home Score", home_sequence),
                f"home score values: {shown.get('Home Score', [])[:20]}",
            ),
            Check(
                f"{self.name}: final state {self.final}",
                self.final_seen_at is not None,
                "" if self.final_seen_at is not None else f"values seen: {shown}",
            ),
        ]


def parse_json_readings(body: bytes) -> dict[str, tuple[str, str]]:
    """GET /json (or the API's JSON (Full) body): [{name, text, state, rect}]."""
    return {item["name"]: (item["text"], item["state"]) for item in json.loads(body)}


def parse_csv_pivot_readings(body: bytes) -> dict[str, tuple[str, str]]:
    """GET /csv?pivot: a row of box names and a row of their good readings."""
    rows = list(csv.reader(io.StringIO(body.decode("utf-8"))))
    if len(rows) < 2:
        return {}
    return {name: (text, "Success") for name, text in zip(rows[0], rows[1])}


def parse_csv_rows(body: bytes) -> list[list[str]]:
    """GET /csv: a Name,Text,X,Y,Width,Height header and a row per box."""
    return list(csv.reader(io.StringIO(body.decode("utf-8"))))


def parse_xml_readings(body: bytes) -> dict[str, tuple[str, str]]:
    """GET /xml: <data><result name= result= result_state= .../></data>."""
    root = ET.fromstring(body)
    return {
        r.get("name"): (r.get("result"), r.get("result_state"))
        for r in root.iter("result")
    }


def overlay_readings(fields: dict) -> dict[str, tuple[str, str]]:
    """The overlays' fields ({box: {value, state}}): the value is the box's last
    good reading, or null before its first one."""
    return {
        box: (field["value"], "Success")
        if field.get("value") is not None
        else ("", "Empty")
        for box, field in fields.items()
    }


def parse_overlay_state(body: bytes) -> dict[str, tuple[str, str]]:
    """GET /overlay/state: {"version": n, "fields": {box: {value, state}}}."""
    return overlay_readings(json.loads(body)["fields"])


class EventStreamHistory(OutputHistory):
    """The browser overlays' push: one /events connection (Server-Sent Events)
    read on a thread for the whole run. Each snapshot or change updates the
    fields, and every update is recorded."""

    def __init__(self, allowed, final):
        super().__init__("/events (push)", allowed, final)
        # reentrant: checks() calls sequence_seen()
        self._lock = threading.RLock()
        self._connection: http.client.HTTPConnection | None = None
        self._thread: threading.Thread | None = None
        self.events = 0
        self.error: str | None = None

    def start(self, port: int):
        self._connection = http.client.HTTPConnection(
            app_harness.LOCALHOST, port, timeout=15
        )
        self._thread = threading.Thread(
            target=self._read, name="e2e-events", daemon=True
        )
        self._thread.start()

    def _read(self):
        fields: dict = {}
        try:
            self._connection.request("GET", "/events")
            response = self._connection.getresponse()
            event, data = "message", ""
            while True:
                line = response.readline()
                if not line:
                    return  # the server stopped
                line = line.decode("utf-8").rstrip("\r\n")
                if line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:"):
                    data = line[5:].strip()
                elif not line and data:
                    message = json.loads(data)
                    if event == "snapshot":
                        fields = dict(message["fields"])
                    elif event == "change":
                        fields.update(message["fields"])
                        for box in message.get("removed", []):
                            fields.pop(box, None)
                    if event in ("snapshot", "change"):
                        with self._lock:
                            self.events += 1
                            self.add(overlay_readings(fields))
                    event, data = "message", ""
        except (OSError, http.client.HTTPException, ValueError, KeyError) as e:
            self.error = f"{type(e).__name__}: {e}"

    def stop(self):
        if self._connection is not None:
            self._connection.close()
        if self._thread is not None:
            self._thread.join(5)

    def sequence_seen(self, box: str, expected: list[str]) -> bool:
        with self._lock:
            return super().sequence_seen(box, expected)

    def checks(self, home_sequence: list[str]) -> list[Check]:
        with self._lock:
            checks = super().checks(home_sequence)
        checks.insert(
            0,
            Check(
                "/events (push): the stream sent the snapshot and the changes",
                self.events > 1,
                f"{self.events} events" + (f"; {self.error}" if self.error else ""),
            ),
        )
        return checks


def read_file_readings(output_dir: Path) -> dict[str, tuple[str, str]]:
    """The .txt files (one per box; only good readings are written)."""
    readings = {}
    for box in BOXES:
        try:
            text = (output_dir / f"{box}.txt").read_text(encoding="utf-8")
        except OSError:
            continue
        readings[box] = (text, "Success")
    return readings


def read_xml_file_readings(output_dir: Path) -> dict[str, tuple[str, str]]:
    """results.xml: <data><result><name/><text/><state/>...</result></data>."""
    try:
        root = ET.parse(output_dir / "results.xml").getroot()
    except (OSError, ET.ParseError):
        return {}
    readings = {}
    for result in root.iter("result"):
        name = result.findtext("name")
        text = result.findtext("text") or ""
        if name and text:
            readings[name] = (text, result.findtext("state") or "Success")
    return readings


def read_csv_file_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    """results.csv (appended): the header and a {box: value} per row."""
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f))
    if not rows:
        return [], []
    header = rows[0]
    return header, [dict(zip(header[1:], row[1:])) for row in rows[1:]]


# --- the run --------------------------------------------------------------------


@dataclass
class Result:
    passed: bool = False
    checks: list[Check] = field(default_factory=list)
    timings: dict[str, float | None] = field(default_factory=dict)
    exit_code: int | None = None
    startup_report: dict | None = None
    details: dict = field(default_factory=dict)

    def check(self, name: str, passed: bool, detail: str = "") -> bool:
        self.checks.append(Check(name, bool(passed), detail))
        return bool(passed)

    def to_json(self) -> dict:
        return {
            "passed": self.passed,
            "timings": self.timings,
            "exit_code": self.exit_code,
            "checks": [check.__dict__ for check in self.checks],
            "startup_report": self.startup_report,
            "details": self.details,
        }


def _get(port: int, path: str) -> bytes | None:
    try:
        status, body = app_harness.http_get(port, path)
    except (OSError, http.client.HTTPException):
        return None
    return body if status == 200 else None


class ApiHistory(OutputHistory):
    """What the mock API endpoint received: POSTed JSON (Full) bodies."""

    def __init__(self, receiver: MockReceiver, allowed, final):
        super().__init__("outbound API", allowed, final)
        self.receiver = receiver
        self.read = 0

    def update(self):
        requests = self.receiver.snapshot()
        for at, method, _path, body in requests[self.read :]:
            if method != "POST":
                self.invalid.append(f"unexpected {method} request")
                continue
            try:
                self.add(parse_json_readings(body), at)
            except (ValueError, KeyError, TypeError) as e:
                self.invalid.append(f"unreadable body ({e}): {body[:100]!r}")
        self.read = len(requests)


class Outputs:
    """The history of every output, sampled while the app runs."""

    def __init__(self, port: int, output_dir: Path, receiver: MockReceiver, timeline):
        self.port = port
        self.output_dir = output_dir
        self.allowed = allowed_values(timeline)
        self.final = timeline[-1][0].values()
        self.home_sequence = collapse([state.home for state, _ in timeline])
        self.histories = {
            name: OutputHistory(name, self.allowed, self.final)
            for name in (
                "GET /json",
                "GET /csv?pivot",
                "GET /xml",
                ".txt files",
                "results.xml",
                "GET /overlay/state",
            )
        }
        self.api = ApiHistory(receiver, self.allowed, self.final)
        self.histories["outbound API"] = self.api
        self.events = EventStreamHistory(self.allowed, self.final)
        self.histories["/events (push)"] = self.events

    def sample(self) -> dict[str, tuple[str, str]] | None:
        """Read every output once. Returns GET /json's readings."""
        now = time.perf_counter()
        readings = None
        body = _get(self.port, "/json")
        if body is not None:
            readings = parse_json_readings(body)
            self.histories["GET /json"].add(readings, now)
        for path, name, parse in (
            ("/csv?pivot", "GET /csv?pivot", parse_csv_pivot_readings),
            ("/xml", "GET /xml", parse_xml_readings),
            ("/overlay/state", "GET /overlay/state", parse_overlay_state),
        ):
            body = _get(self.port, path)
            if body is not None:
                self.histories[name].add(parse(body), now)
        self.histories[".txt files"].add(read_file_readings(self.output_dir), now)
        self.histories["results.xml"].add(read_xml_file_readings(self.output_dir), now)
        self.api.update()
        return readings

    def complete(self) -> bool:
        """Whether every output showed the home score's sequence and the final
        state."""
        return all(
            h.final_seen_at is not None
            and h.sequence_seen("Home Score", self.home_sequence)
            for h in self.histories.values()
        )


def drive(app, outputs: Outputs, result: Result, timeout: float) -> bool:
    """Sample the outputs until each showed the full sequence and the final
    state, or until timeout seconds after the app started. Returns False if
    the HTTP server never answered."""
    ready = app_harness.wait_for_http(app, outputs.port, timeout)
    result.timings["http_ready"] = ready
    if not result.check("the HTTP server answers GET /json", ready is not None):
        return False
    # the overlays' push, followed over one connection until the app stops
    outputs.events.start(outputs.port)

    deadline = app.started + timeout
    first_reading = None
    while time.perf_counter() < deadline and app.running():
        readings = outputs.sample()
        if first_reading is None and any(
            state in GOOD_STATES for _, state in (readings or {}).values()
        ):
            first_reading = app.elapsed()
        if outputs.complete():
            break
        time.sleep(0.1)

    result.timings["first_reading"] = first_reading
    json_final = outputs.histories["GET /json"].final_seen_at
    result.timings["final_state"] = (
        None if json_final is None else json_final - app.started
    )
    result.check(
        "the app is still running", app.running(), f"exit code {app.process.poll()}"
    )
    result.check("a first reading within the timeout", first_reading is not None)

    # the full /csv: a header and a row per box (with any reading's text)
    body = _get(outputs.port, "/csv")
    rows = parse_csv_rows(body) if body is not None else []
    result.check(
        "GET /csv has a header and a row per box",
        rows[:1] == [["Name", "Text", "X", "Y", "Width", "Height"]]
        and sorted(row[0] for row in rows[1:] if row) == sorted(BOXES),
        f"{rows[:5]}",
    )
    return True


def check_outputs(result: Result, outputs: Outputs) -> None:
    outputs.api.update()
    for history in outputs.histories.values():
        result.checks.extend(history.checks(outputs.home_sequence))

    # results.csv: a row appended per change, a single header
    csv_path = outputs.output_dir / "results.csv"
    if result.check("results.csv was written", csv_path.is_file()):
        header, rows = read_csv_file_rows(csv_path)
        result.check(
            "results.csv has the boxes as columns",
            header == ["Timestamp", *BOXES],
            f"header {header}",
        )
        history = OutputHistory("results.csv", outputs.allowed, outputs.final)
        for row in rows:
            # a box without a reading yet is empty
            history.add(
                {box: (v, "Success" if v else "Empty") for box, v in row.items()}
            )
        outputs.histories["results.csv"] = history
        result.checks.extend(history.checks(outputs.home_sequence))

    result.details["outputs"] = {
        name: {
            "samples": h.samples,
            "values": {box: collapse(v) for box, v in h.values.items()},
            "invalid": h.invalid[:50],
            "transient": h.transient,
        }
        for name, h in outputs.histories.items()
    }


def check_settings(result: Result, data_dir: Path, engine: str = "ppocr") -> None:
    path = settings_path(data_dir)
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        result.check("the settings file is valid JSON", False, str(e))
        return
    result.check("the settings file is valid JSON", True)
    names = [box.get("name") for box in settings.get("boxes") or []]
    result.check(
        "the settings file still has the boxes", names == list(BOXES), f"{names}"
    )
    expected_model = (
        OCR_MODEL_PPOCR_DEFAULT if engine == "ppocr" else OCR_MODEL_GENERAL_SCOREBOARD
    )
    result.check(
        f"the settings file has the OCR model {expected_model!r}",
        settings.get("ocr_model") == expected_model,
        f"ocr_model: {settings.get('ocr_model')!r}",
    )


def read_logs(log_dir: Path) -> str:
    """The text of the app's log files."""
    if not Path(log_dir).is_dir():
        return ""
    return "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in sorted(Path(log_dir).glob("*.log"))
    )


def check_engine(result: Result, log_dir: Path, engine: str) -> None:
    """The log shows the chosen engine reading (not a fallback)."""
    logs = read_logs(log_dir)
    line = ENGINE_LOG_LINES[engine]
    result.check(f"the app read with {engine} (log: {line!r})", line in logs)
    if engine == "ppocr":
        result.check(
            "PP-OCR didn't fall back to Tesseract",
            PPOCR_FALLBACK_LOG_LINE not in logs,
        )
        # not a failure: a slow runner may need the fast model
        result.details["ppocr_auto_switched_to_fast"] = PPOCR_AUTO_FAST_LOG_LINE in logs


def run_e2e(
    command: list[str], timeout: float, work_dir: Path, engine: str = "ppocr"
) -> Result:
    result = Result()
    data_dir, log_dir = work_dir / "data", work_dir / "logs"
    output_dir = work_dir / "output"
    for directory in (data_dir, log_dir, output_dir):
        directory.mkdir(parents=True, exist_ok=True)
    timeline = build_timeline()
    video = work_dir / "scoreboard.avi"
    frames = write_video(video, timeline)
    result.details["video"] = {"frames": frames, "fps": FPS}
    result.details["engine"] = engine
    print(f"video: {video} ({frames} frames), OCR engine: {engine}", flush=True)

    receiver = MockReceiver()
    receiver.start()
    settings_path(data_dir).write_text(
        json.dumps(app_settings(video, output_dir, receiver.url, engine), indent=2),
        encoding="utf-8",
    )
    port = app_harness.free_port()
    report_path = work_dir / "startup-report.json"
    env = app_harness.app_env(
        data_dir, log_dir, SCORESIGHT_STARTUP_REPORT=str(report_path)
    )
    full_command = [*command, "--profile", PROFILE, "--port", str(port)]
    print(f"$ {subprocess.list2cmdline(full_command)}", flush=True)
    app = app_harness.AppProcess(full_command, env, work_dir / "app-output.txt")
    outputs = Outputs(port, output_dir, receiver, timeline)
    try:
        answered = drive(app, outputs, result, timeout)
        stop_started = time.perf_counter()
        result.exit_code = app.stop(timeout=30)
        # the server ended the stream when it stopped
        outputs.events.stop()
        result.timings["shutdown"] = time.perf_counter() - stop_started
        result.check(
            "the app quits with exit code 0 when asked to",
            result.exit_code == 0,
            "it was killed" if result.exit_code is None else f"{result.exit_code}",
        )
        if answered:
            check_outputs(result, outputs)
        check_settings(result, data_dir, engine)
        check_engine(result, log_dir, engine)
        try:
            result.startup_report = json.loads(report_path.read_text("utf-8"))
        except (OSError, ValueError):
            result.startup_report = None
        result.check(
            "the startup report was written", result.startup_report is not None
        )
    finally:
        outputs.events.stop()
        app.close()
        receiver.stop()
    result.passed = all(check.passed for check in result.checks)
    if not result.passed:
        app_harness.print_diagnostics(app, log_dir)
    return result


# --- reporting ------------------------------------------------------------------


def _seconds(value) -> str:
    return "-" if value is None else f"{value:.2f} s"


def format_summary(result: Result, label: str) -> str:
    """Markdown for the job summary."""
    status = "passed" if result.passed else "FAILED"
    failed = [c for c in result.checks if not c.passed]
    lines = [
        f"### End-to-end test ({label}): {status}",
        "",
        "| Step | Time |",
        "|---|---|",
        f"| HTTP server answers | {_seconds(result.timings.get('http_ready'))} |",
        f"| first reading | {_seconds(result.timings.get('first_reading'))} |",
        f"| final state read | {_seconds(result.timings.get('final_state'))} |",
        f"| quit (exit code {result.exit_code}) | "
        f"{_seconds(result.timings.get('shutdown'))} |",
        "",
        f"{len(result.checks) - len(failed)}/{len(result.checks)} checks passed.",
    ]
    for check in failed:
        lines.append(
            f"- FAILED: {check.name}" + (f": {check.detail}" if check.detail else "")
        )
    return "\n".join(lines)


def print_result(result: Result) -> None:
    for check in result.checks:
        mark = "ok  " if check.passed else "FAIL"
        detail = f" ({check.detail})" if check.detail and not check.passed else ""
        print(f"[{mark}] {check.name}{detail}")
    timings = ", ".join(f"{k} {_seconds(v)}" for k, v in result.timings.items())
    print(f"timings: {timings}")
    if result.startup_report and result.startup_report.get("total") is not None:
        print(f"in-app startup total: {_seconds(result.startup_report['total'])}")
    print("E2E PASSED" if result.passed else "E2E FAILED", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0],
        usage="%(prog)s [options] -- <app command...>",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=180,
        help="seconds from the start of the app to the end of the checks "
        "(default: %(default)s)",
    )
    parser.add_argument(
        "--engine",
        choices=ENGINES,
        default="ppocr",
        help="the OCR engine: ppocr (a new setup's default, PP-OCR accurate) or "
        "tesseract (General Scoreboard) (default: %(default)s)",
    )
    parser.add_argument("--json", type=Path, help="write the results to this file")
    parser.add_argument("--label", default="", help="name of the run in the summary")
    parser.add_argument(
        "--work-dir",
        type=Path,
        help="keep the video, settings, logs and outputs in this folder "
        "(default: a temporary folder that is deleted)",
    )
    parser.add_argument("command", nargs=argparse.REMAINDER, help="the app command")
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("give the app command after --")
    label = f"{args.label or Path(command[-1]).name}, {args.engine}"
    try:
        command = app_harness.resolve_command(command)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    if args.work_dir:
        args.work_dir.mkdir(parents=True, exist_ok=True)
        result = run_e2e(command, args.timeout, args.work_dir.resolve(), args.engine)
    else:
        with tempfile.TemporaryDirectory(
            prefix="scoresight-e2e-", ignore_cleanup_errors=True
        ) as tmp:
            result = run_e2e(command, args.timeout, Path(tmp), args.engine)
    print_result(result)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "label": label,
            "engine": args.engine,
            "command": command,
            **result.to_json(),
        }
        args.json.write_text(json.dumps(data, indent=2), encoding="utf-8")
    app_harness.append_step_summary(format_summary(result, label))
    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
