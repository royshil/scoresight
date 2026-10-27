"""The built-in HTTP server: serves the latest OCR results as JSON, XML, CSV and a
demo HTML scoreboard.

/json, /xml and /csv give every box with its state; "?pivot" gives
{name: text} of the latest cycle's good readings. For programs that poll and
bind by column or row, "?pivot&all" gives every box with its last good
reading ("" before the first), and /json?array (also /json?pivot&array) the
same object in a list, the shape vMix Data Sources read. Responses are never
cached, and pages anywhere (also public ones, for the local network) may read
them.

It runs uvicorn in a daemon thread, bound to 0.0.0.0 (LAN access is a feature)
on the port given to start_http_server(). It is stopped in-process by
stop_http_server(); there is no HTTP endpoint that stops or kills the app.
"""

import csv
import logging
import os
import re
import socket
import sys
import threading
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from io import StringIO
from typing import NamedTuple

import uvicorn
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response

import startup_timing
from game_state import GameState
from overlay_feed import feed as overlay_feed
from overlays import router as overlays_router
from sc_logging import file_handler, logger
from text_detection_target import TextDetectionTargetWithResult

DEFAULT_PORT = 18099
HOST = "0.0.0.0"

ResultState = TextDetectionTargetWithResult.ResultState
# readings that are worth showing; the ?pivot variants include only these
_GOOD_STATES = frozenset({ResultState.Success.name, ResultState.SameNoChange.name})


class Reading(NamedTuple):
    """An immutable copy of one OCR result, safe to read from the server thread."""

    name: str
    text: str
    state: str  # a ResultState name
    x: float
    y: float
    width: float
    height: float

    @property
    def is_good(self) -> bool:
        return self.state in _GOOD_STATES

    def to_dict(self) -> dict:
        # same shape as TextDetectionTargetWithResult.to_dict()
        return {
            "name": self.name,
            "text": self.text,
            "state": self.state,
            "rect": {
                "x": self.x,
                "y": self.y,
                "width": self.width,
                "height": self.height,
            },
        }


# The latest results. update_http_server() (GUI thread) replaces the whole tuple,
# the request handlers (server thread) only read it.
_readings: tuple[Reading, ...] = ()
# Every box with its last good reading ("" before its first), in the boxes'
# order, for "?pivot&all" and "?array": replaced as a whole like _readings.
_last_good_values: tuple[tuple[str, str], ...] = ()
# the last good text of each box (GUI thread only)
_last_good: dict[str, str] = {}

# Programs that poll the data (browser sources, vMix, XPression, Windows
# components with their own HTTP cache) must always get the latest values.
NO_CACHE_HEADERS = {
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
}

app = FastAPI(title="ScoreSight")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # browser sources and pages from anywhere may read
    allow_methods=["GET"],
    allow_headers=["*"],
    # a page on a public site may read a ScoreSight on the local network
    # (Chromium's Private Network Access preflight)
    allow_private_network=True,
)

# --- request statistics (for the window's output status) -----------------------

# a client that made a request within this many seconds counts as connected
RECENT_CLIENT_S = 10.0
# at most this many client addresses are remembered
_MAX_CLIENTS = 64

_stats_lock = threading.Lock()
_request_count = 0
_last_request_at: float | None = None
_client_seen_at: dict[str, float] = {}


def _record_request(client, new_request: bool = True) -> None:
    global _request_count, _last_request_at
    now = time.monotonic()
    host = client[0] if client else "?"
    with _stats_lock:
        if new_request:
            _request_count += 1
            _last_request_at = now
        _client_seen_at[host] = now
        if len(_client_seen_at) > _MAX_CLIENTS:
            # forget the client seen longest ago
            del _client_seen_at[min(_client_seen_at, key=_client_seen_at.get)]


class _RequestCounter:
    """ASGI middleware that counts the requests (a lock and a few integers: it
    never slows a request down). A long response (the overlays' live stream,
    /events) keeps its client counted as recent while it sends."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        client = scope.get("client")
        _record_request(client)

        async def send_and_record(message):
            if message["type"] == "http.response.body" and message.get("more_body"):
                _record_request(client, new_request=False)
            await send(message)

        await self.app(scope, receive, send_and_record)


app.add_middleware(_RequestCounter)

# the overlays: /events, /overlay/... (overlays.py)
app.include_router(overlays_router)


@dataclass(frozen=True)
class HttpServerStats:
    requests: int = 0  # requests served since ScoreSight started
    last_request_at: float | None = None  # time.monotonic()
    recent_clients: int = 0  # addresses that made a request recently
    # why the server isn't running, if it couldn't start
    start_error: str | None = None


def http_server_stats(now: float | None = None) -> HttpServerStats:
    """The request statistics (thread-safe)."""
    now = time.monotonic() if now is None else now
    with _stats_lock:
        recent = sum(
            1 for seen in _client_seen_at.values() if now - seen <= RECENT_CLIENT_S
        )
        stats = (_request_count, _last_request_at, recent)
    with _server_lock:
        start_error = _start_error
    return HttpServerStats(*stats, start_error=start_error)


HTML_PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Scoreboard</title>
<style>
  body { font-family: Arial, sans-serif; text-align: center; }
  .scoreboard { display: flex; justify-content: normal; align-items: center; margin-top: 20px; }
  .team { width: 25%; }
  .info { background: #f0f0f0; padding: 20px; border-radius: 10px; }
  .team-name { font-size: 24px; margin-bottom: 10px; }
  .score { font-size: 48px; margin-bottom: 10px; }
  .timer { font-size: 78px; margin: 0 20px; }
  .fouls { font-size: 24px; }
</style>
</head>
<body>
<script>
  function updateScoreboard() {
    // relative URL: works from any computer and on any --port
    fetch('/json')
      .then(response => response.json())
      .then(data => {
        if (data.find(item => item.name === 'Home Score') !== undefined) {
          const homeScore = data.find(item => item.name === 'Home Score').text;
          document.querySelector('.team.home .score').textContent = homeScore;
        }

        if (data.find(item => item.name === 'Away Score') !== undefined) {
          const awayScore = data.find(item => item.name === 'Away Score').text;
          document.querySelector('.team.away .score').textContent = awayScore;
        }

        if (data.find(item => item.name === 'Home Fouls') !== undefined) {
          const homeFouls = data.find(item => item.name === 'Home Fouls').text;
          document.querySelector('.team.home .fouls').textContent = `Fouls: ${homeFouls}`;
        }

        if (data.find(item => item.name === 'Away Fouls') !== undefined) {
          const awayFouls = data.find(item => item.name === 'Away Fouls').text;
          document.querySelector('.team.away .fouls').textContent = `Fouls: ${awayFouls}`;
        }

        if (data.find(item => item.name === 'Time') !== undefined) {
          const timeItem = data.find(item => item.name === 'Time');
          if (timeItem.state === 'Success' || timeItem.state === 'SameNoChange') {
            const time = timeItem.text;
            document.querySelector('.timer').textContent = time;
          }
        }
      })
      .catch(error => console.error('Error:', error));
  }

  setInterval(updateScoreboard, 100);
</script>

<div class="scoreboard">
  <div class="team home">
    <div class="info">
      <div class="team-name">Home Team</div>
      <div class="score">0</div>
      <div class="fouls">Fouls: 0</div>
    </div>
  </div>
  <div class="timer">00:00</div>
  <div class="team away">
    <div class="info">
      <div class="team-name">Away Team</div>
      <div class="score">0</div>
      <div class="fouls">Fouls: 0</div>
    </div>
  </div>
</div>

</body>
</html>
"""

# XML 1.0 (5th edition) name characters, without ":" (reserved for namespaces)
_XML_NAME_START_CHARS = (
    "A-Z_a-z\u00c0-\u00d6\u00d8-\u00f6\u00f8-\u02ff\u0370-\u037d\u037f-\u1fff"
    "\u200c-\u200d\u2070-\u218f\u2c00-\u2fef\u3001-\ud7ff\uf900-\ufdcf"
    "\ufdf0-\ufffd\U00010000-\U000effff"
)
_XML_NAME_CHARS = _XML_NAME_START_CHARS + "\\-.0-9\u00b7\u0300-\u036f\u203f-\u2040"
_NOT_XML_NAME_CHAR = re.compile(f"[^{_XML_NAME_CHARS}]")
_XML_NAME_START = re.compile(f"[{_XML_NAME_START_CHARS}]")
# characters that XML 1.0 doesn't allow anywhere in a document
_NOT_XML_CHAR = re.compile("[^\t\n\r\u0020-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]")


def xml_element_name(name: str) -> str:
    """The element name used for a box in /xml?pivot.

    Each word is capitalized and the spaces are removed ("Home Score" becomes
    "HomeScore"). Characters that aren't allowed in XML names are dropped, and
    "_" is prepended when the result doesn't start with a letter or "_"
    ("1st Half" becomes "_1StHalf", "Score (H)" becomes "ScoreH").
    """
    tag = _NOT_XML_NAME_CHAR.sub("", "".join(word.title() for word in name.split()))
    if not tag or not _XML_NAME_START.match(tag):
        tag = "_" + tag
    return tag


def xml_text(text: str) -> str:
    """text without the control characters XML can't represent."""
    return _NOT_XML_CHAR.sub("", text)


def _good_values() -> dict[str, str]:
    return {r.name: r.text for r in _readings if r.is_good}


def _pivot_values(all_boxes: str | None) -> dict[str, str]:
    """{name: text} for a ?pivot variant: the good readings of the latest
    cycle, or with "&all" every box with its last good reading ("" before its
    first), so columns never come and go for readers that bind by column."""
    if all_boxes is not None:
        return dict(_last_good_values)
    return _good_values()


# "&all": every box, each with its last good value
_ALL_QUERY = Query(None, alias="all")


@app.get("/scoresight", response_class=HTMLResponse)
async def get_html():
    return HTMLResponse(content=HTML_PAGE, headers=NO_CACHE_HEADERS)


@app.get("/json")
async def get_json(
    pivot: str | None = Query(None),
    all_boxes: str | None = _ALL_QUERY,
    array: str | None = Query(None),
):
    # "?array" (for vMix Data Sources and other readers of rows): the
    # "?pivot&all" object in a list, [{name: last good text, ...}]
    if array is not None:
        return JSONResponse(content=[dict(_last_good_values)], headers=NO_CACHE_HEADERS)
    # "?pivot": {name: text} of the good readings only
    if pivot is not None:
        return JSONResponse(content=_pivot_values(all_boxes), headers=NO_CACHE_HEADERS)
    return JSONResponse(
        content=[r.to_dict() for r in _readings], headers=NO_CACHE_HEADERS
    )


# the game, as the game-state engine follows it (MainWindow publishes it with
# every cycle's readings: update_game_state)
_game_state = GameState(sport="none", roles={})


@app.get("/game")
async def get_game(since: int = Query(0)):
    """The game: the sport, the scores, clock, period, fouls and timeouts, the
    points of each period, and the events (those after event id "since")."""
    return JSONResponse(content=_game_state.to_dict(since), headers=NO_CACHE_HEADERS)


def update_game_state(state: GameState):
    """Publish the game's state (a snapshot) for /game."""
    global _game_state
    _game_state = state


@app.get("/xml")
async def get_xml(pivot: str | None = Query(None), all_boxes: str | None = _ALL_QUERY):
    root = ET.Element("data")
    if pivot is not None:
        for name, text in _pivot_values(all_boxes).items():
            ET.SubElement(root, xml_element_name(name)).text = xml_text(text)
    else:
        for r in _readings:
            result_el = ET.SubElement(root, "result")
            result_el.set("name", xml_text(r.name))
            result_el.set("result", xml_text(r.text))
            result_el.set("result_state", r.state)
            result_el.set("x", str(r.x))
            result_el.set("y", str(r.y))
            result_el.set("width", str(r.width))
            result_el.set("height", str(r.height))

    # sent as UTF-8 ("text/xml; charset=utf-8"): character references can't
    # represent non-ASCII letters in element names
    return Response(
        content=ET.tostring(root, encoding="unicode"),
        media_type="text/xml",
        headers=NO_CACHE_HEADERS,
    )


@app.get("/csv")
async def get_csv(pivot: str | None = Query(None), all_boxes: str | None = _ALL_QUERY):
    output = StringIO()
    csv_writer = csv.writer(output)
    if pivot is not None:
        # one header row with the box names, one row with their good values
        values = _pivot_values(all_boxes)
        csv_writer.writerow(values.keys())
        csv_writer.writerow(values.values())
    else:
        csv_writer.writerow(["Name", "Text", "X", "Y", "Width", "Height"])
        for r in _readings:
            csv_writer.writerow([r.name, r.text, r.x, r.y, r.width, r.height])
    return Response(
        content=output.getvalue(), media_type="text/csv", headers=NO_CACHE_HEADERS
    )


def update_http_server(results: list[TextDetectionTargetWithResult]):
    """Publish the latest OCR results. Takes a snapshot, so the caller may keep
    modifying the result objects afterwards."""
    global _readings, _last_good_values
    readings = tuple(
        Reading(
            name=str(r.name),
            text="" if r.result is None else str(r.result),
            state=r.result_state.name,
            x=r.x(),
            y=r.y(),
            width=r.width(),
            height=r.height(),
        )
        for r in results
    )
    # the last good reading of each box; a box that is gone is forgotten
    names = {r.name for r in readings}
    for name in [name for name in _last_good if name not in names]:
        del _last_good[name]
    for r in readings:
        if r.is_good:
            _last_good[r.name] = r.text
    _readings = readings
    _last_good_values = tuple((r.name, _last_good.get(r.name, "")) for r in readings)
    # the overlays' live values (pushes only what changed)
    overlay_feed.publish(_readings)


# --- server lifecycle -----------------------------------------------------

_server_lock = threading.Lock()
_server: uvicorn.Server | None = None
_server_thread: threading.Thread | None = None
_server_port: int | None = None
# why the last start_http_server() call couldn't start the server
_start_error: str | None = None


def bind_socket(host: str, port: int) -> socket.socket:
    """Bind and listen on (host, port). Raises OSError if the port is taken."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if sys.platform == "win32":
            # never share the port: a second ScoreSight must fail here instead
            # of silently splitting the requests with the first one
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            # allow a quick restart while old connections are in TIME_WAIT (on
            # POSIX this never allows binding a port another socket listens on)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, port))
        # listen right away: requests that arrive before uvicorn's loop runs
        # wait in the backlog instead of being refused
        sock.listen(128)
    except OSError:
        sock.close()
        raise
    return sock


class _Server(uvicorn.Server):
    """uvicorn's server, which marks the startup milestone once it serves."""

    async def startup(self, sockets=None):
        await super().startup(sockets=sockets)
        if self.started:
            startup_timing.mark("http_server_ready")


def _serve(server: uvicorn.Server, sock: socket.socket, port: int) -> None:
    try:
        server.run(sockets=[sock])
    except (Exception, SystemExit):  # uvicorn calls sys.exit() on startup errors
        logger.exception("HTTP server on port %s failed", port)
    finally:
        sock.close()
        logger.info("HTTP server on port %s stopped", port)


def start_http_server(port: int = DEFAULT_PORT) -> None:
    """Start serving on port (0 picks a free port, see get_http_server_port()).

    Never raises: if the port is already in use (for example by another
    ScoreSight), the error is logged and the app continues without the server.
    """
    global _server, _server_thread, _server_port, _start_error
    with _server_lock:
        if _server_thread is not None and _server_thread.is_alive():
            logger.warning("HTTP server is already running on port %s", _server_port)
            return
        try:
            sock = bind_socket(HOST, port)
        except OSError as e:
            _start_error = f"{type(e).__name__}: {e}"
            logger.error(
                "HTTP server: port %s is already in use or not available (%s). "
                "Another ScoreSight or another program may be using it; start "
                "ScoreSight with --port to use a different port. Continuing "
                "without the HTTP server.",
                port,
                e,
            )
            return

        _start_error = None
        actual_port = sock.getsockname()[1]
        debug = bool(os.getenv("SCORESIGHT_DEBUG"))
        for name in ("uvicorn.error", "uvicorn.access"):
            logging.getLogger(name).addHandler(file_handler)
        config = uvicorn.Config(
            app=app,
            host=HOST,
            port=actual_port,
            loop="asyncio",
            log_level="debug" if debug else "info",
            log_config=None,
            # one line per request (pages poll several times a second) only
            # when debugging
            access_log=debug,
            lifespan="off",
            ws="none",
            # don't wait long for polling clients' keep-alive connections
            timeout_graceful_shutdown=1,
        )
        server = _Server(config)
        thread = threading.Thread(
            target=_serve,
            args=(server, sock, actual_port),
            name="http-server",
            daemon=True,
        )
        _server, _server_thread, _server_port = server, thread, actual_port
        thread.start()
    logger.info("HTTP server listening on http://%s:%s", HOST, actual_port)


def get_http_server_port() -> int | None:
    """The port the server listens on, or None if it isn't running."""
    with _server_lock:
        if _server_thread is not None and _server_thread.is_alive():
            return _server_port
        return None


def stop_http_server(timeout: float = 3.0) -> None:
    """Stop the server this process started, waiting at most timeout seconds.

    A no-op if it isn't running (e.g. the port was busy at startup): it never
    touches a server that belongs to another process. The thread is a daemon,
    so even a server that doesn't stop in time can't keep the app from exiting.
    """
    global _server, _server_thread, _server_port
    with _server_lock:
        server, thread = _server, _server_thread
        _server = _server_thread = _server_port = None
    if server is None or thread is None:
        return

    logger.info("Stopping HTTP server...")
    # end the overlays' live streams, so the server doesn't wait for them
    overlay_feed.close_streams()
    server.should_exit = True
    thread.join(timeout / 2)
    if thread.is_alive():
        # stop waiting for open connections and background tasks
        server.force_exit = True
        thread.join(timeout / 2)
    if thread.is_alive():
        logger.warning("HTTP server did not stop within %.1fs", timeout)
