"""The phone camera source (src/phone_camera.py): its certificate, access key,
frames, HTTPS server and capture."""

import json
import ssl
import urllib.error
import urllib.request

import cv2
import numpy as np
import pytest

import phone_camera
from phone_camera import PhoneCapture, PhoneFeed


class FakeClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


# --- the certificate and the access key -----------------------------------------


def test_the_certificate_is_made_once_and_kept(tmp_path):
    from cryptography import x509

    cert_path, key_path = phone_camera.certificate_files(tmp_path)
    cert_pem = cert_path.read_bytes()
    cert = x509.load_pem_x509_certificate(cert_pem)
    names = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert "localhost" in names.get_values_for_type(x509.DNSName)
    assert "127.0.0.1" in [str(a) for a in names.get_values_for_type(x509.IPAddress)]
    days = (cert.not_valid_after_utc - cert.not_valid_before_utc).days
    # phones refuse server certificates valid longer than 825 days
    assert days <= phone_camera.CERT_VALID_DAYS + 1
    # it loads as a server certificate
    ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER).load_cert_chain(cert_path, key_path)

    # kept: a phone that accepted it isn't asked again
    phone_camera.certificate_files(tmp_path)
    assert cert_path.read_bytes() == cert_pem


def test_a_certificate_about_to_expire_is_made_again(tmp_path, monkeypatch):
    monkeypatch.setattr(phone_camera, "CERT_VALID_DAYS", phone_camera.CERT_RENEW_DAYS)
    cert_path, _ = phone_camera.certificate_files(tmp_path)
    first = cert_path.read_bytes()
    phone_camera.certificate_files(tmp_path)
    assert cert_path.read_bytes() != first


def test_a_damaged_certificate_is_made_again(tmp_path):
    cert_path, _ = phone_camera.certificate_files(tmp_path)
    cert_path.write_text("not a certificate")
    phone_camera.certificate_files(tmp_path)
    assert cert_path.read_text().startswith("-----BEGIN CERTIFICATE-----")


def test_the_access_key_is_kept(tmp_path):
    key = phone_camera.access_key(tmp_path)
    assert len(key) >= 16
    assert phone_camera.access_key(tmp_path) == key
    (tmp_path / phone_camera.ACCESS_KEY_FILE).write_text("short")
    assert phone_camera.access_key(tmp_path) not in ("short", key)


# --- the frames ------------------------------------------------------------------


def test_the_latest_frame_is_waited_for():
    feed = PhoneFeed(FakeClock())
    assert feed.wait_for_frame(0, timeout=0) is None
    assert feed.push("a", b"1")
    assert feed.push("a", b"2")
    assert feed.wait_for_frame(0, timeout=0) == (2, b"2")
    assert feed.wait_for_frame(2, timeout=0) is None


def test_a_page_opened_later_takes_over():
    feed = PhoneFeed(FakeClock())
    assert feed.push("first", b"1")
    assert feed.push("second", b"2")
    # the first page is told to stop, and doesn't take over again
    assert not feed.push("first", b"3")
    assert feed.wait_for_frame(0, timeout=0) == (2, b"2")
    assert feed.push("second", b"4")


def test_a_phone_counts_as_sending_while_its_frames_are_recent():
    clock = FakeClock()
    feed = PhoneFeed(clock)
    assert not feed.is_sending() and not feed.has_sent()
    feed.push("a", b"1")
    assert feed.is_sending()
    clock.now += phone_camera.FRAME_TIMEOUT_S + 0.1
    assert not feed.is_sending()
    assert feed.has_sent()


@pytest.mark.parametrize(
    "interval, expected",
    [(None, phone_camera.DEFAULT_INTERVAL_MS), (33, 100), (250, 250), (10000, 1000)],
)
def test_the_phone_sends_at_the_detection_cadence(interval, expected):
    feed = PhoneFeed()
    feed.interval_provider = None if interval is None else (lambda: interval)
    # at most 10 frames a second, and at least one (the preview)
    assert feed.interval_ms() == expected


# --- the server and the capture --------------------------------------------------


def jpeg(width=64, height=48):
    frame = np.zeros((height, width, 3), np.uint8)
    frame[:, : width // 2] = (0, 0, 255)
    return cv2.imencode(".jpg", frame)[1].tobytes()


@pytest.fixture
def phone(tmp_path, monkeypatch, qapp):
    """A started PhoneCapture on a free port, and an HTTPS opener that trusts
    its certificate."""
    monkeypatch.setattr(phone_camera, "feed", PhoneFeed())
    capture = PhoneCapture(interval_ms=lambda: 250, port=0, directory=tmp_path)
    context = ssl.create_default_context(cafile=tmp_path / phone_camera.CERT_FILE)
    capture.base = f"https://localhost:{capture.port}"
    capture.key = phone_camera.access_key(tmp_path)
    capture.context = context
    yield capture
    capture.release()
    phone_camera.stop_server()


def request(phone, path, data=None, headers=None):
    req = urllib.request.Request(phone.base + path, data=data, headers=headers or {})
    try:
        with urllib.request.urlopen(req, context=phone.context, timeout=5) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def send(phone, frame, session="phone-1", key=None):
    status, body = request(
        phone,
        "/camera/frame",
        data=frame,
        headers={
            "Content-Type": "image/jpeg",
            "X-Access-Key": phone.key if key is None else key,
            "X-Session": session,
        },
    )
    return status, json.loads(body)


@pytest.mark.qt
def test_the_page_is_served_over_https_with_the_key(phone):
    status, body = request(phone, f"/camera?k={phone.key}")
    assert status == 200
    assert b"ScoreSight camera" in body
    assert request(phone, "/camera?k=wrong")[0] == 403
    assert request(phone, "/camera")[0] == 403
    assert phone.url().endswith(f":{phone.port}/camera?k={phone.key}")


@pytest.mark.qt
def test_frames_need_the_key(phone):
    assert send(phone, jpeg(), key="wrong")[0] == 403
    assert phone_camera.feed.wait_for_frame(0, timeout=0) is None


@pytest.mark.qt
def test_the_capture_reads_the_phones_frames(phone):
    # no phone yet: the waiting picture, which the capture thread doesn't read
    ok, picture = phone.read()
    assert ok and phone.showing_placeholder
    assert picture.shape == (720, 1280, 3)

    status, reply = send(phone, jpeg(64, 48))
    assert status == 200
    assert reply == {"active": True, "interval_ms": 250}
    ok, frame = phone.read()
    assert ok and not phone.showing_placeholder
    assert frame.shape == (48, 64, 3)
    assert frame[24, 10, 2] > 200  # red on the left

    # between the phone's frames, the last one again
    ok, again = phone.read()
    assert ok and again is frame


@pytest.mark.qt
def test_a_second_phone_takes_over(phone):
    assert send(phone, jpeg(), session="first")[1]["active"]
    assert send(phone, jpeg(32, 32), session="second")[1]["active"]
    assert send(phone, jpeg(), session="first")[1]["active"] is False
    ok, frame = phone.read()
    assert frame.shape == (32, 32, 3)


@pytest.mark.qt
def test_a_frame_that_is_not_an_image_is_skipped(phone):
    send(phone, jpeg(64, 48))
    phone.read()
    send(phone, b"not a jpeg")
    ok, frame = phone.read()
    # the last good frame
    assert ok and frame.shape == (48, 64, 3)
