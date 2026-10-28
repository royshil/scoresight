"""The phone camera source: a phone's browser sends its camera to ScoreSight
over the local network, without an app.

Phone browsers open the camera only on an HTTPS page, so ScoreSight serves the
phone's page (phone/camera.html) over HTTPS, on the port after the HTTP
server's (18100 by default), with a self-signed certificate made once per
install: the phone shows a certificate warning the first time, which the user
taps through. The page sends JPEG frames (POST /camera/frame) at the detection
cadence; PhoneCapture gives the capture thread the latest one.

The page's address carries an access key (in the QR code ScoreSight shows), so
nobody else on the network can send frames. One phone sends at a time: a page
opened later takes over, and the earlier one is told to stop.

The server starts with the first phone camera source and runs until
stop_server() (at exit). cryptography (the certificate) and segno (the QR
code) are imported when first needed.
"""

import datetime
import ipaddress
import os
import secrets
import socket
import threading
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path

import cv2
import numpy as np
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from PySide6.QtCore import QCoreApplication, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter

import http_server
from base_video_capture import BaseVideoCapture
from resource_path import resource_path
from sc_logging import logger
from storage import get_data_dir

HOST = "0.0.0.0"
# the HTTPS server's port is the HTTP server's plus this
PORT_OFFSET = 1
PAGE_PATH = "/camera"

CERT_FILE = "phone-camera-cert.pem"
KEY_FILE = "phone-camera-key.pem"
ACCESS_KEY_FILE = "phone-camera-access-key.txt"
# the longest validity phones accept for a TLS server certificate (825 days);
# a certificate this close to expiring is made again
CERT_VALID_DAYS = 825
CERT_RENEW_DAYS = 30

# a frame bigger than this is refused (a 4K JPEG is about 2 MB)
MAX_FRAME_BYTES = 8 * 1024 * 1024
# the phone counts as sending while its last frame is this recent
FRAME_TIMEOUT_S = 3.0
# PhoneCapture.read() waits this long for a new frame
READ_WAIT_S = 0.5
# the phone sends a frame per detection, at most this often, and at least once
# a second (the preview)
MIN_INTERVAL_MS = 100
MAX_INTERVAL_MS = 1000
DEFAULT_INTERVAL_MS = 200

# the waiting picture's size
PLACEHOLDER_SIZE = (1280, 720)

ACCESS_KEY_HEADER = "X-Access-Key"
SESSION_HEADER = "X-Session"


# --- the certificate and the access key ---------------------------------------


def _local_addresses() -> list[str]:
    """The IPv4 addresses the phone may reach this computer at."""
    from status_bar import primary_lan_address

    addresses = []
    primary = primary_lan_address()
    if primary:
        addresses.append(primary)
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    except OSError:
        infos = []
    for info in infos:
        address = info[4][0]
        if address not in addresses and not address.startswith(("127.", "169.254.")):
            addresses.append(address)
    return addresses


def _certificate_usable(cert_path: Path, key_path: Path) -> bool:
    from cryptography import x509

    if not cert_path.is_file() or not key_path.is_file():
        return False
    try:
        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    except (OSError, ValueError):
        return False
    renew_at = cert.not_valid_after_utc - datetime.timedelta(days=CERT_RENEW_DAYS)
    return datetime.datetime.now(datetime.timezone.utc) < renew_at


def _write_private(path: Path, data: bytes) -> None:
    """Write data to a file only its owner may read (where the OS allows)."""
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def make_certificate(cert_path: Path, key_path: Path) -> None:
    """A self-signed certificate (and its key) for this computer's names and
    addresses. Phones don't trust it either way (the user taps through the
    warning once); the names only make the warning name this computer."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    hostname = socket.gethostname() or "scoresight"
    names: list[x509.GeneralName] = [x509.DNSName("localhost")]
    for name in (hostname, f"{hostname}.local"):
        try:
            names.append(x509.DNSName(name.encode("idna").decode("ascii")))
        except (UnicodeError, ValueError):
            pass
    for address in ["127.0.0.1", *_local_addresses()]:
        names.append(x509.IPAddress(ipaddress.ip_address(address)))
    subject = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, f"ScoreSight on {hostname}"[:64])]
    )
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=CERT_VALID_DAYS))
        .add_extension(x509.SubjectAlternativeName(names), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), True)
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
        )
        .sign(key, hashes.SHA256())
    )
    cert_path.parent.mkdir(parents=True, exist_ok=True)
    _write_private(
        key_path,
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
    )
    _write_private(cert_path, cert.public_bytes(serialization.Encoding.PEM))
    logger.info("Phone camera: made a certificate for %s", hostname)


def certificate_files(directory: Path) -> tuple[Path, Path]:
    """The certificate and key files in directory, made if missing or about
    to expire."""
    cert_path, key_path = directory / CERT_FILE, directory / KEY_FILE
    if not _certificate_usable(cert_path, key_path):
        make_certificate(cert_path, key_path)
    return cert_path, key_path


def access_key(directory: Path) -> str:
    """The key the phone's page must send with its frames (kept, so a phone's
    page keeps working after ScoreSight restarts)."""
    path = directory / ACCESS_KEY_FILE
    try:
        key = path.read_text(encoding="ascii").strip()
    except (OSError, UnicodeError):
        key = ""
    if len(key) < 16:
        key = secrets.token_urlsafe(12)
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_private(path, key.encode("ascii"))
    return key


# --- the frames ---------------------------------------------------------------


class PhoneFeed:
    """The latest frame from the phone (thread-safe: the server thread pushes,
    the capture thread waits for frames)."""

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._cond = threading.Condition()
        self._seq = 0
        self._jpeg: bytes | None = None
        self._received_at: float | None = None
        self._session: str | None = None
        # the sessions another page took over from (they are told to stop)
        self._replaced: deque[str] = deque(maxlen=32)
        # the time between frames the phone is asked for, in ms
        self.interval_provider: Callable[[], float] | None = None

    def push(self, session: str, jpeg: bytes, client: str = "?") -> bool:
        """Take a frame from a phone's page; False if that page was replaced
        by another one (it should stop)."""
        with self._cond:
            if session in self._replaced:
                return False
            if session != self._session:
                if self._session is not None:
                    self._replaced.append(self._session)
                    logger.info("Phone camera: another page (%s) took over", client)
                else:
                    logger.info("Phone camera: %s is sending", client)
                self._session = session
            elif not self._is_sending():
                logger.info("Phone camera: %s is sending again", client)
            self._seq += 1
            self._jpeg = jpeg
            self._received_at = self._clock()
            self._cond.notify_all()
            return True

    def _is_sending(self) -> bool:
        return (
            self._received_at is not None
            and self._clock() - self._received_at <= FRAME_TIMEOUT_S
        )

    def is_sending(self) -> bool:
        """Whether a phone sent a frame recently."""
        with self._cond:
            return self._is_sending()

    def has_sent(self) -> bool:
        """Whether a phone has sent a frame since ScoreSight started."""
        with self._cond:
            return self._received_at is not None

    def wait_for_frame(self, after: int, timeout: float) -> tuple[int, bytes] | None:
        """(sequence number, JPEG) of the latest frame, once there is one newer
        than sequence number after; None after timeout seconds without one."""
        with self._cond:
            if self._cond.wait_for(lambda: self._seq > after, timeout):
                return self._seq, self._jpeg
            return None

    def interval_ms(self) -> int:
        provider = self.interval_provider
        try:
            interval = float(provider()) if provider else DEFAULT_INTERVAL_MS
        except Exception:
            interval = DEFAULT_INTERVAL_MS
        return int(min(MAX_INTERVAL_MS, max(MIN_INTERVAL_MS, interval)))


feed = PhoneFeed()


# --- the HTTPS server ---------------------------------------------------------

app = FastAPI(title="ScoreSight phone camera", docs_url=None, redoc_url=None)
# set by start_server()
_access_key: str | None = None


def _key_ok(key: str | None) -> bool:
    expected = _access_key
    return bool(expected and key and secrets.compare_digest(key, expected))


_FORBIDDEN_PAGE = """<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ScoreSight</title></head>
<body style="font-family: sans-serif; background: #0B1220; color: #F5F7FA;
padding: 24px; font-size: 18px">
<p>Scan the code ScoreSight shows for the phone camera again: this address is
missing its key, or is from another ScoreSight.</p></body></html>"""


@app.get("/")
async def get_root(request: Request):
    query = request.url.query
    return RedirectResponse(PAGE_PATH + (f"?{query}" if query else ""))


@app.get(PAGE_PATH)
async def get_page(k: str | None = None):
    if not _key_ok(k):
        return HTMLResponse(_FORBIDDEN_PAGE, status_code=403)
    with open(resource_path("phone", "camera.html"), encoding="utf-8") as f:
        page = f.read()
    return HTMLResponse(page, headers=http_server.NO_CACHE_HEADERS)


@app.post(PAGE_PATH + "/frame")
async def post_frame(request: Request):
    if not _key_ok(request.headers.get(ACCESS_KEY_HEADER)):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    session = request.headers.get(SESSION_HEADER, "")[:64]
    try:
        length = int(request.headers.get("content-length", "0"))
    except ValueError:
        length = 0
    if not session or length > MAX_FRAME_BYTES:
        return JSONResponse({"error": "bad request"}, status_code=400)
    jpeg = await request.body()
    if not jpeg or len(jpeg) > MAX_FRAME_BYTES:
        return JSONResponse({"error": "bad request"}, status_code=400)
    client = request.client.host if request.client else "?"
    active = feed.push(session, jpeg, client)
    return JSONResponse(
        {"active": active, "interval_ms": feed.interval_ms()},
        headers=http_server.NO_CACHE_HEADERS,
    )


_server_lock = threading.Lock()
_server: uvicorn.Server | None = None
_server_thread: threading.Thread | None = None
_server_port: int | None = None


def preferred_port() -> int:
    """The HTTP server's port plus PORT_OFFSET (18100 by default)."""
    http_port = http_server.get_http_server_port() or http_server.DEFAULT_PORT
    return http_port + PORT_OFFSET


def _serve(server: uvicorn.Server, sock: socket.socket, port: int) -> None:
    try:
        server.run(sockets=[sock])
    except (Exception, SystemExit):  # uvicorn calls sys.exit() on startup errors
        logger.exception("Phone camera server on port %s failed", port)
    finally:
        sock.close()
        logger.info("Phone camera server on port %s stopped", port)


def start_server(port: int | None = None, directory: Path | None = None) -> int:
    """Start the HTTPS server, if it isn't running; returns its port. It
    listens on port (default: preferred_port()), or on a free port if that one
    is taken. Raises OSError (or a certificate error) if it can't start."""
    global _server, _server_thread, _server_port, _access_key
    with _server_lock:
        if _server_thread is not None and _server_thread.is_alive():
            return _server_port
        directory = Path(get_data_dir()) if directory is None else directory
        cert_path, key_path = certificate_files(directory)
        _access_key = access_key(directory)
        port = preferred_port() if port is None else port
        try:
            sock = http_server.bind_socket(HOST, port)
        except OSError as e:
            logger.warning("Phone camera: port %s is not available (%s)", port, e)
            sock = http_server.bind_socket(HOST, 0)
        actual_port = sock.getsockname()[1]
        config = uvicorn.Config(
            app=app,
            host=HOST,
            port=actual_port,
            loop="asyncio",
            log_level="info",
            log_config=None,
            access_log=False,
            lifespan="off",
            ws="none",
            ssl_certfile=str(cert_path),
            ssl_keyfile=str(key_path),
            timeout_graceful_shutdown=1,
        )
        try:
            # loads the certificate now, so an error is raised here
            config.load()
        except BaseException:
            sock.close()
            raise
        server = uvicorn.Server(config)
        thread = threading.Thread(
            target=_serve,
            args=(server, sock, actual_port),
            name="phone-camera-server",
            daemon=True,
        )
        _server, _server_thread, _server_port = server, thread, actual_port
        thread.start()
    logger.info("Phone camera server listening on https://%s:%s", HOST, actual_port)
    return actual_port


def server_port() -> int | None:
    """The HTTPS server's port, or None if it isn't running."""
    with _server_lock:
        if _server_thread is not None and _server_thread.is_alive():
            return _server_port
        return None


def stop_server(timeout: float = 2.0) -> None:
    """Stop the HTTPS server, if it runs (a daemon thread: it never keeps the
    app from exiting)."""
    global _server, _server_thread, _server_port
    with _server_lock:
        server, thread = _server, _server_thread
        _server = _server_thread = _server_port = None
    if server is None or thread is None:
        return
    server.should_exit = True
    thread.join(timeout / 2)
    if thread.is_alive():
        server.force_exit = True
        thread.join(timeout / 2)


def page_url(port: int, address: str | None = None) -> str:
    """The phone's page, with the access key."""
    if address is None:
        addresses = _local_addresses()
        address = addresses[0] if addresses else socket.gethostname()
    return f"https://{address}:{port}{PAGE_PATH}?k={_access_key or ''}"


# --- the waiting picture -------------------------------------------------------


def _qimage_to_bgr(image: QImage) -> np.ndarray:
    image = image.convertToFormat(QImage.Format.Format_BGR888)
    width, height = image.width(), image.height()
    data = np.frombuffer(image.constBits(), np.uint8)
    rows = data.reshape(height, image.bytesPerLine())
    return rows[:, : width * 3].reshape(height, width, 3).copy()


def render_placeholder(url: str, stopped: bool) -> np.ndarray:
    """The picture shown while no phone sends: the page's QR code and address,
    and what to do (a BGR image)."""
    import segno

    width, height = PLACEHOLDER_SIZE
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor("#0B1220"))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

    # the QR code on a white card
    qr = segno.make(url, error="m")
    rows = list(qr.matrix_iter(scale=1, border=4))
    card = 440
    left, top = 72, (height - card) // 2
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#FFFFFF"))
    painter.drawRoundedRect(QRectF(left, top, card, card), 16, 16)
    module = card / len(rows)
    painter.setBrush(QColor("#000000"))
    for y, row in enumerate(rows):
        for x, dark in enumerate(row):
            if dark:
                # a hair bigger, so no seams show between modules
                painter.drawRect(
                    QRectF(
                        left + x * module, top + y * module, module + 0.5, module + 0.5
                    )
                )

    def text(rect, string, size, color, weight=QFont.Weight.Normal, flags=0):
        font = QFont()
        font.setPixelSize(size)
        font.setWeight(weight)
        painter.setFont(font)
        painter.setPen(QColor(color))
        painter.drawText(QRectF(*rect), int(flags), string)

    x = left + card + 64
    w = width - x - 56
    wrap = Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignLeft
    text(
        (x, top, w, 56),
        QCoreApplication.translate("PhoneCamera", "Phone camera"),
        44,
        "#F5F7FA",
        QFont.Weight.Bold,
    )
    status = (
        QCoreApplication.translate("PhoneCamera", "The phone stopped sending.")
        if stopped
        else QCoreApplication.translate("PhoneCamera", "Waiting for the phone…")
    )
    text((x, top + 64, w, 44), status, 30, "#FFB020", QFont.Weight.DemiBold)
    steps = "\n".join(
        (
            QCoreApplication.translate(
                "PhoneCamera",
                "1. Connect the phone to the same network as this computer.",
            ),
            QCoreApplication.translate(
                "PhoneCamera", "2. Scan this code with the phone's camera."
            ),
            QCoreApplication.translate(
                "PhoneCamera",
                "3. The phone warns that the connection isn't private: "
                "ScoreSight's certificate is its own. Continue to the page "
                "(Show details or Advanced).",
            ),
            QCoreApplication.translate(
                "PhoneCamera", "4. Point the phone at the scoreboard and tap Start."
            ),
        )
    )
    text((x, top + 132, w, 210), steps, 22, "#C9D2E0", flags=wrap)
    text(
        (x, top + 340, w, 30),
        QCoreApplication.translate("PhoneCamera", "Or open this address on the phone:"),
        20,
        "#9AA7BD",
    )
    text(
        (x, top + 372, w, 68),
        url,
        20,
        "#3DA5FF",
        flags=Qt.TextFlag.TextWrapAnywhere | Qt.AlignmentFlag.AlignLeft,
    )
    painter.end()
    return _qimage_to_bgr(image)


# --- the capture --------------------------------------------------------------


class PhoneCapture(BaseVideoCapture):
    """The video capture of the phone camera source. Starts the HTTPS server.

    read() gives the phone's latest frame. While no phone sends, it gives the
    waiting picture, with showing_placeholder set: the capture thread shows it
    as it is and doesn't read it (OCR)."""

    def __init__(
        self,
        interval_ms: Callable[[], float] | None = None,
        port: int | None = None,
        directory: Path | None = None,
    ):
        super().__init__("phone")
        self.port = start_server(port, directory)
        feed.interval_provider = interval_ms
        self.showing_placeholder = False
        self._seq = 0
        self._frame: np.ndarray | None = None
        self._placeholder: tuple[tuple, np.ndarray] | None = None
        self._open = True
        logger.info("Phone camera: open %s on the phone", self.url())

    def url(self) -> str:
        return page_url(self.port)

    def isOpened(self):
        return self._open

    def release(self):
        # the server keeps running: the phone's page reconnects to the next
        # phone camera source
        self._open = False
        feed.interval_provider = None

    def read(self):
        latest = feed.wait_for_frame(self._seq, READ_WAIT_S)
        # (a frame kept from before this source opened may be old)
        if latest is not None and feed.is_sending():
            self._seq, jpeg = latest
            frame = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
            if frame is not None:
                self._frame = frame
                self.showing_placeholder = False
                return True, frame
            logger.warning("Phone camera: a frame couldn't be decoded")
        if self._frame is not None and feed.is_sending():
            # between the phone's frames
            return True, self._frame
        if self._frame is not None:
            logger.info("Phone camera: the phone stopped sending")
        self._frame = None
        self.showing_placeholder = True
        return True, self.placeholder()

    def placeholder(self) -> np.ndarray:
        key = (self.url(), feed.has_sent())
        if self._placeholder is None or self._placeholder[0] != key:
            self._placeholder = (key, render_placeholder(*key))
        return self._placeholder[1]

    def set(self, propId, value):
        return False

    def get(self, propId):
        if propId == cv2.CAP_PROP_FRAME_WIDTH and self._frame is not None:
            return float(self._frame.shape[1])
        if propId == cv2.CAP_PROP_FRAME_HEIGHT and self._frame is not None:
            return float(self._frame.shape[0])
        return 0.0


def self_test(directory: Path) -> str:
    """Make a certificate in directory, load it as the server would, and draw
    the waiting picture (for main's --self-test)."""
    import ssl

    cert_path, key_path = certificate_files(directory)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_path, key_path)
    picture = render_placeholder("https://192.0.2.1:18100/camera?k=self-test", False)
    return f"certificate made, waiting picture {picture.shape[1]}x{picture.shape[0]}"
