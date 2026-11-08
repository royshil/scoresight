"""update_check: version comparison, GitHub response parsing and the dialog."""

import pytest
import requests

import update_check
from storage import fetch_data
from update_check import (
    LATEST_RELEASE_API_URL,
    LATEST_RELEASE_PAGE_URL,
    RELEASES_API_URL,
    check_for_updates,
    is_newer_version,
    latest_release_from_response,
    parse_version,
)


# the real one: the autouse fixture below replaces it in update_check
needs_intel_mac_build = update_check.needs_intel_mac_build


class FakeResponse:
    def __init__(self, payload=None, status_code=200, json_error=False):
        self._payload = payload
        self.status_code = status_code
        self._json_error = json_error

    def json(self):
        if self._json_error:
            raise ValueError("not JSON")
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")


class FakeGet:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.urls = []

    def __call__(self, url):
        self.urls.append(url)
        if self.error is not None:
            raise self.error
        return self.response


def release(tag, draft=False, prerelease=False, intel_mac=True):
    version = tag.removeprefix("v")
    names = ["windows-x64-setup.exe", "macos-arm64.dmg"]
    if intel_mac:
        names.append("macos-x64.dmg")
    return {
        "tag_name": tag,
        "draft": draft,
        "prerelease": prerelease,
        "html_url": f"https://github.com/royshil/scoresight/releases/tag/{tag}",
        "assets": [{"name": f"scoresight-{version}-{name}"} for name in names],
    }


@pytest.fixture(autouse=True)
def not_an_intel_mac(monkeypatch):
    """The tests don't depend on the machine they run on."""
    monkeypatch.setattr(update_check, "needs_intel_mac_build", lambda: False)


# --- versions --------------------------------------------------------------------


@pytest.mark.parametrize(
    "text", ["0.2.0", "v0.2.0", " 1.10.3 ", "0.2.0-beta.1", "0.2.0-rc.12", "1.0.0+b5"]
)
def test_parse_valid_versions(text):
    assert parse_version(text) is not None


@pytest.mark.parametrize("text", ["", "0.2", "0.2.0.1", "latest", "01.2.3", None, 2])
def test_parse_invalid_versions(text):
    assert parse_version(text) is None


@pytest.mark.parametrize(
    ("older", "newer"),
    [
        ("0.1.0", "0.2.0"),
        ("0.2.0", "0.2.1"),
        ("0.9.0", "0.10.0"),  # numeric, not lexical
        ("0.2.0", "1.0.0"),
        ("0.2.0-beta.1", "0.2.0-beta.2"),
        ("0.2.0-beta.2", "0.2.0-beta.10"),
        ("0.2.0-beta.3", "0.2.0-rc.1"),
        ("0.2.0-rc.1", "0.2.0"),  # a release is newer than its prereleases
        ("0.1.9", "0.2.0-beta.1"),
        ("v0.1.0", "0.1.1"),
    ],
)
def test_version_precedence(older, newer):
    assert is_newer_version(newer, older)
    assert not is_newer_version(older, newer)


def test_same_or_unparseable_version_is_not_newer():
    assert not is_newer_version("0.2.0", "0.2.0")
    assert not is_newer_version("v0.2.0", "0.2.0")
    assert not is_newer_version("nightly", "0.2.0")
    assert not is_newer_version("0.3.0", "dev")


# --- GitHub responses ---------------------------------------------------------------


def test_latest_release_ignores_drafts_and_prereleases():
    payload = [
        release("0.4.0", draft=True),
        release("0.3.0-rc.1", prerelease=True),
        release("0.3.0-beta.1"),  # a prerelease tag even if not flagged
        release("0.2.1"),
        release("0.2.0"),
        {"tag_name": "not-a-version"},
    ]
    assert latest_release_from_response(payload, False)["tag_name"] == "0.2.1"
    assert latest_release_from_response(payload, True)["tag_name"] == "0.3.0-rc.1"


def test_latest_release_handles_empty_and_odd_payloads():
    assert latest_release_from_response([], False) is None
    assert latest_release_from_response({"message": "Not Found"}, False) is None
    assert latest_release_from_response("garbage", False) is None


def test_update_available():
    get = FakeGet(FakeResponse(release("0.3.0")))
    result = check_for_updates("0.2.0", get)
    assert get.urls == [LATEST_RELEASE_API_URL]
    assert result.update_available
    assert result.latest_version == "0.3.0"
    assert result.error is None
    assert result.release_url == LATEST_RELEASE_PAGE_URL


def test_up_to_date():
    result = check_for_updates("0.3.0", FakeGet(FakeResponse(release("0.3.0"))))
    assert not result.update_available
    assert result.latest_version == "0.3.0"
    assert result.error is None


def test_running_a_newer_build_than_the_latest_release():
    result = check_for_updates(
        "0.4.0-beta.1", FakeGet(FakeResponse([release("0.3.0")]))
    )
    assert not result.update_available


def test_prerelease_users_are_offered_newer_prereleases():
    get = FakeGet(
        FakeResponse(
            [
                release("0.3.0-rc.2", prerelease=True),
                release("0.3.0-rc.1"),
                release("0.2.0"),
            ]
        )
    )
    result = check_for_updates("0.3.0-rc.1", get)
    assert get.urls == [RELEASES_API_URL]
    assert result.update_available
    assert result.latest_version == "0.3.0-rc.2"
    assert result.release_url.endswith("/releases/tag/0.3.0-rc.2")


def test_stable_users_are_not_offered_a_prerelease_marked_latest():
    payload = release("0.3.0-rc.1", prerelease=True)
    result = check_for_updates("0.2.0", FakeGet(FakeResponse(payload)))
    assert not result.update_available
    assert result.latest_version is None


# --- Intel Macs (0.4.4 is their last release) ---------------------------------------


def test_an_intel_mac_is_not_offered_a_release_without_its_build(monkeypatch):
    monkeypatch.setattr(update_check, "needs_intel_mac_build", lambda: True)
    payload = [release("0.5.0", intel_mac=False), release("0.4.4")]
    get = FakeGet(FakeResponse(payload))
    result = check_for_updates("0.4.4", get)
    assert get.urls == [RELEASES_API_URL]
    assert not result.update_available
    assert result.latest_version == "0.4.4"
    assert result.error is None


def test_an_intel_mac_is_offered_the_newest_release_with_its_build(monkeypatch):
    monkeypatch.setattr(update_check, "needs_intel_mac_build", lambda: True)
    payload = [
        release("0.5.0", intel_mac=False),
        release("0.4.5"),
        release("0.4.4"),
    ]
    result = check_for_updates("0.4.3", FakeGet(FakeResponse(payload)))
    assert result.update_available
    assert result.latest_version == "0.4.5"
    # /releases/latest would be 0.5.0: the dialog links to 0.4.5's page
    assert result.release_url == payload[1]["html_url"]


def test_other_computers_are_offered_a_release_without_an_intel_mac_build():
    result = check_for_updates(
        "0.4.4", FakeGet(FakeResponse(release("0.5.0", intel_mac=False)))
    )
    assert result.update_available
    assert result.latest_version == "0.5.0"


@pytest.mark.parametrize(
    "system, machine, rosetta, expected",
    [
        ("darwin", "x86_64", False, True),
        ("darwin", "x86_64", True, False),  # the Intel build on Apple Silicon
        ("darwin", "arm64", False, False),
        ("win32", "AMD64", False, False),
        ("linux", "x86_64", False, False),
    ],
)
def test_which_computers_need_an_intel_mac_build(
    monkeypatch, system, machine, rosetta, expected
):
    monkeypatch.setattr(update_check.sys, "platform", system)
    monkeypatch.setattr(update_check.platform, "machine", lambda: machine)
    monkeypatch.setattr(update_check, "_running_under_rosetta", lambda: rosetta)
    assert needs_intel_mac_build() is expected


def test_rosetta_check_never_raises():
    assert update_check._running_under_rosetta() in (True, False)


def test_no_published_release_is_not_an_error():
    result = check_for_updates("0.2.0", FakeGet(FakeResponse(status_code=404)))
    assert not result.update_available
    assert result.error is None


@pytest.mark.parametrize(
    "get",
    [
        FakeGet(error=requests.ConnectionError("offline")),
        FakeGet(error=requests.Timeout("too slow")),
        FakeGet(FakeResponse(status_code=403)),  # e.g. API rate limit
        FakeGet(FakeResponse(json_error=True)),
    ],
)
def test_failures_are_reported_not_raised(get):
    result = check_for_updates("0.2.0", get)
    assert not result.update_available
    assert result.error


def test_default_request_has_timeout_and_user_agent(monkeypatch):
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse(release("0.2.0"))

    monkeypatch.setattr(update_check.requests, "get", fake_get)
    check_for_updates("0.2.0")
    [(url, kwargs)] = calls
    assert url == LATEST_RELEASE_API_URL
    assert kwargs["timeout"]
    assert kwargs["headers"]["User-Agent"].startswith("ScoreSight/")


# --- setting and dialog -------------------------------------------------------------


def test_startup_checks_enabled_by_default():
    assert update_check.update_checks_enabled()


@pytest.mark.qt
@pytest.mark.parametrize(
    ("result", "visible"),
    [
        (
            update_check.UpdateCheckResult("0.2.0", "0.3.0", update_available=True),
            "label_newVersion",
        ),
        (update_check.UpdateCheckResult("0.3.0", "0.3.0"), "label_noNewVersion"),
        (update_check.UpdateCheckResult("0.2.0", error="offline"), "label_error"),
    ],
)
def test_dialog_shows_the_result(qapp, result, visible):
    dialog = update_check.create_update_dialog(result)
    labels = ("label_newVersion", "label_noNewVersion", "label_error")
    assert [n for n in labels if not getattr(dialog.ui, n).isHidden()] == [visible]
    assert "0.2.0" in dialog.ui.label_versions.text() or "0.3.0" in (
        dialog.ui.label_versions.text()
    )
    for name in labels:
        text = getattr(dialog.ui, name).text()
        assert "scoresight.live" not in text
        assert "color:#" not in text
    dialog.deleteLater()


@pytest.mark.qt
def test_dialog_checkbox_toggles_the_startup_check(qapp):
    dialog = update_check.create_update_dialog(update_check.UpdateCheckResult("0.2.0"))
    assert not dialog.ui.checkBox_disableUpdateChecks.isChecked()
    dialog.ui.checkBox_disableUpdateChecks.setChecked(True)
    assert fetch_data("scoresight.json", "disable_update_checks") is True
    assert not update_check.update_checks_enabled()
    dialog.deleteLater()
