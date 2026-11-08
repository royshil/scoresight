"""Check GitHub Releases for a newer ScoreSight version.

check_for_updates() is blocking (one HTTPS request with a short timeout) and
never raises; MainWindow runs it on a worker thread and shows the result with
show_update_dialog() on the GUI thread.

Versions are compared with semantic-versioning precedence (X.Y.Z, optionally
-beta.N / -rc.N, with or without a leading "v"). Draft releases are ignored, and
so are prereleases unless the running version is itself a prerelease.
"""

import re
from dataclasses import dataclass
from typing import Callable

import requests
from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QWidget

from app_update import InstallerAsset, installer_asset
from sc_logging import logger
from storage import fetch_data, store_data
from ui_update_available import Ui_Dialog as Ui_UpdateAvailable
from version import __version__

GITHUB_REPO = "royshil/scoresight"
LATEST_RELEASE_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases"
LATEST_RELEASE_PAGE_URL = f"https://github.com/{GITHUB_REPO}/releases/latest"

# (connect, read) timeouts in seconds
REQUEST_TIMEOUT = (3.05, 5)

# Setting written by the "Don't check for updates at startup" checkbox. Manual
# checks (File > Check for Updates) always run.
DISABLE_UPDATE_CHECKS_KEY = "disable_update_checks"

_VERSION_RE = re.compile(
    r"^v?(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<pre>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+[0-9A-Za-z.-]+)?$"
)


@dataclass(frozen=True, order=True)
class Version:
    """A parsed semantic version. Instances sort by SemVer precedence."""

    major: int
    minor: int
    patch: int
    # 1 for a release, 0 for a prerelease: a release sorts after its prereleases
    is_release: int
    # prerelease identifiers: numeric ones sort before alphanumeric ones
    pre: tuple[tuple[int, int | str], ...]

    @property
    def is_prerelease(self) -> bool:
        return not self.is_release


def parse_version(text: str | None) -> Version | None:
    """Parse "0.2.0", "v0.2.0", "0.2.0-beta.1" or "0.2.0-rc.2"; None if invalid."""
    if not isinstance(text, str):
        return None
    match = _VERSION_RE.match(text.strip())
    if not match:
        return None
    pre = match.group("pre")
    identifiers = tuple(
        (0, int(part)) if part.isdigit() else (1, part)
        for part in (pre.split(".") if pre else [])
    )
    return Version(
        int(match.group("major")),
        int(match.group("minor")),
        int(match.group("patch")),
        0 if pre else 1,
        identifiers,
    )


def is_newer_version(candidate: str, current: str) -> bool:
    """True if version string candidate is newer than current. Unparseable
    versions are never newer."""
    candidate_version = parse_version(candidate)
    current_version = parse_version(current)
    if candidate_version is None or current_version is None:
        return False
    return candidate_version > current_version


@dataclass
class UpdateCheckResult:
    current_version: str
    latest_version: str | None = None
    release_url: str = LATEST_RELEASE_PAGE_URL
    update_available: bool = False
    error: str | None = None
    # the new version's Windows installer, for Update now (app_update.py)
    installer: InstallerAsset | None = None


def _release_version(release) -> tuple[Version, dict] | None:
    if not isinstance(release, dict) or release.get("draft"):
        return None
    version = parse_version(release.get("tag_name"))
    if version is None:
        return None
    return version, release


def latest_release_from_response(payload, include_prereleases: bool) -> dict | None:
    """The newest usable release in a GitHub API response: a release object (from
    /releases/latest) or a list of them (from /releases)."""
    releases = payload if isinstance(payload, list) else [payload]
    candidates = []
    for release in releases:
        parsed = _release_version(release)
        if parsed is None:
            continue
        version, release = parsed
        if (version.is_prerelease or release.get("prerelease")) and (
            not include_prereleases
        ):
            continue
        candidates.append(parsed)
    if not candidates:
        return None
    return max(candidates, key=lambda parsed: parsed[0])[1]


def _http_get(url: str):
    return requests.get(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"ScoreSight/{__version__}",
        },
        timeout=REQUEST_TIMEOUT,
    )


def check_for_updates(
    current_version: str = __version__, http_get: Callable = _http_get
) -> UpdateCheckResult:
    """Query GitHub for the latest release and compare it with current_version.

    Blocking; call it from a worker thread. Never raises: failures are reported
    in UpdateCheckResult.error.
    """
    result = UpdateCheckResult(current_version=current_version)
    current = parse_version(current_version)
    # A prerelease user is told about newer prereleases too, which
    # /releases/latest never returns.
    include_prereleases = current is not None and current.is_prerelease
    url = RELEASES_API_URL if include_prereleases else LATEST_RELEASE_API_URL
    logger.info("Checking for updates: %s", url)
    try:
        response = http_get(url)
        if response.status_code == 404:
            # /releases/latest answers 404 while there is no published release
            logger.info("No published release found")
            return result
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as e:
        logger.warning("Update check failed: %s", e)
        result.error = str(e)
        return result

    release = latest_release_from_response(payload, include_prereleases)
    if release is None:
        logger.info("No usable release found in the update check response")
        return result
    result.latest_version = str(release["tag_name"]).strip()
    html_url = release.get("html_url")
    if (
        include_prereleases
        and isinstance(html_url, str)
        and html_url.startswith(f"https://github.com/{GITHUB_REPO}/")
    ):
        # /releases/latest never points at a prerelease: link to the release
        result.release_url = html_url
    result.update_available = is_newer_version(result.latest_version, current_version)
    if result.update_available:
        result.installer = installer_asset(release)
    logger.info(
        "Current version: %s, latest release: %s, update available: %s",
        current_version,
        result.latest_version,
        result.update_available,
    )
    return result


def update_checks_enabled() -> bool:
    """Whether the automatic check at startup is enabled."""
    return not fetch_data("scoresight.json", DISABLE_UPDATE_CHECKS_KEY, False)


def create_update_dialog(
    result: UpdateCheckResult,
    parent: QWidget | None = None,
    update_now: Callable[[UpdateCheckResult], None] | None = None,
) -> QDialog:
    """The dialog that reports an update check result (not shown yet). With
    update_now, a new version with a Windows installer gets an Update now
    button, which closes the dialog and calls update_now(result)."""
    dialog = QDialog(parent)
    ui = Ui_UpdateAvailable()
    ui.setupUi(dialog)
    dialog.ui = ui

    # QCoreApplication.translate is called by name, not through an alias, so
    # that pyside6-lupdate finds these strings with their context
    error = result.error is not None
    ui.label_newVersion.setVisible(result.update_available)
    ui.label_noNewVersion.setVisible(not result.update_available and not error)
    ui.label_error.setVisible(error)
    dialog.setWindowTitle(
        QCoreApplication.translate("UpdateCheck", "ScoreSight Update Available")
        if result.update_available
        else QCoreApplication.translate("UpdateCheck", "ScoreSight Update Check")
    )
    versions = QCoreApplication.translate(
        "UpdateCheck", "Installed version: {current}"
    ).format(current=result.current_version)
    if result.latest_version:
        versions += "\n" + QCoreApplication.translate(
            "UpdateCheck", "Latest release: {latest}"
        ).format(latest=result.latest_version)
    ui.label_versions.setText(versions)
    if result.update_available:
        ui.label_newVersion.setText(
            ui.label_newVersion.text().replace(
                LATEST_RELEASE_PAGE_URL, result.release_url
            )
        )

    if update_now is not None and result.update_available and result.installer:
        button = ui.buttonBox.addButton(
            QCoreApplication.translate("UpdateCheck", "Update now"),
            QDialogButtonBox.ButtonRole.ActionRole,
        )
        button.setDefault(True)

        def clicked():
            dialog.accept()
            update_now(result)

        button.clicked.connect(clicked)
        dialog.update_now_button = button

    ui.checkBox_disableUpdateChecks.setChecked(not update_checks_enabled())
    ui.checkBox_disableUpdateChecks.toggled.connect(
        lambda value: store_data("scoresight.json", DISABLE_UPDATE_CHECKS_KEY, value)
    )
    return dialog


def show_update_dialog(
    result: UpdateCheckResult,
    parent: QWidget | None = None,
    update_now: Callable[[UpdateCheckResult], None] | None = None,
) -> QDialog:
    """Show the result dialog without blocking (window-modal over parent)."""
    dialog = create_update_dialog(result, parent, update_now)
    dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    dialog.open()
    return dialog
