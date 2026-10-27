"""The texts of the viewer column's source bar and of the messages around the
picture: what the source combo box shows for the open source, the source error
banner, the four-corner picking banner, the playback speeds, the zoom readout,
the first-run card's links (the Quickstart and the community), and whether
macOS lets ScoreSight record the screen.

MainWindow owns the widgets (they are in mainwindow.ui); this module words
and computes what they show, so it can be tested without a window.
CompactToolRow fits the viewer column's rows into narrow windows.
"""

import platform

from PySide6.QtCore import QCoreApplication, QEvent, QObject, Qt
from PySide6.QtWidgets import QWidget

from camera_info import CameraInfo
from status_bar import without_credentials

DOCS_URL = "https://royshil.github.io/scoresight/"
QUICKSTART_URL = DOCS_URL + "quickstart.html"
SOURCE_TROUBLESHOOTING_URL = DOCS_URL + "troubleshooting.html#source-problems"
# ScoreSight's Discussions on GitHub: questions, ideas, setups to show
COMMUNITY_URL = "https://github.com/royshil/scoresight/discussions"
# System Settings > Privacy & Security > Screen Recording
MACOS_SCREEN_RECORDING_SETTINGS_URL = (
    "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"
)

# the playback speeds of a video file, in the order the speed button cycles
PLAYBACK_SPEEDS = (1, 2, 4, 8, 16, 32)

# the window id of a screen capture of the whole screen
ENTIRE_SCREEN = -1


def file_name(path) -> str:
    path = str(path)
    return path.replace("\\", "/").rsplit("/", 1)[-1] or path


def screen_title(window_id, window_title: str | None = None) -> str:
    """The name of a screen capture's window ("Entire screen" for the whole
    screen)."""
    if window_id == ENTIRE_SCREEN or window_id is None:
        return QCoreApplication.translate("SourceBar", "Entire screen")
    return window_title or QCoreApplication.translate(
        "SourceBar", "Window {id}"
    ).format(id=window_id)


def source_combo_text(
    camera_info: CameraInfo | None, window_title: str | None = None
) -> str | None:
    """What the source combo box shows while a video file, a stream or a
    screen capture is open ("Video file: game.mp4"), or None for the other
    sources (a camera's item already shows its name)."""
    if camera_info is None:
        return None
    if camera_info.type == CameraInfo.CameraType.FILE:
        return QCoreApplication.translate("SourceBar", "Video file: {name}").format(
            name=file_name(camera_info.id)
        )
    if camera_info.type == CameraInfo.CameraType.URL:
        return QCoreApplication.translate("SourceBar", "Stream: {url}").format(
            url=without_credentials(str(camera_info.id))
        )
    if camera_info.type == CameraInfo.CameraType.SCREEN_CAPTURE:
        return QCoreApplication.translate("SourceBar", "Screen: {window}").format(
            window=screen_title(camera_info.id, window_title)
        )
    return None


def source_full_name(
    camera_info: CameraInfo | None, window_title: str | None = None
) -> str:
    """The open source in full: a file's path, a stream's URL (without its
    password), a captured window's title, or a camera's name."""
    if camera_info is None:
        return ""
    if camera_info.type == CameraInfo.CameraType.FILE:
        return str(camera_info.id)
    if camera_info.type == CameraInfo.CameraType.URL:
        return without_credentials(str(camera_info.id))
    if camera_info.type == CameraInfo.CameraType.SCREEN_CAPTURE:
        return screen_title(camera_info.id, window_title)
    return str(camera_info.description)


def chooser_texts() -> tuple[str, str, str, str, str]:
    """The source combo box's first items: no source, the choosers of a
    video file, a stream URL and a screen capture, and the phone camera."""
    return (
        QCoreApplication.translate("MainWindow", "No source"),
        QCoreApplication.translate("MainWindow", "Video file…"),
        QCoreApplication.translate("MainWindow", "Stream URL (RTSP, HTTP)…"),
        QCoreApplication.translate("MainWindow", "Screen capture…"),
        QCoreApplication.translate("MainWindow", "Phone camera"),
    )


def phone_camera_info() -> CameraInfo:
    """The phone camera source (phone_camera.py)."""
    name = QCoreApplication.translate("MainWindow", "Phone camera")
    return CameraInfo(name, "phone", "phone", CameraInfo.CameraType.PHONE)


def source_error_text(
    camera_info: CameraInfo | None, window_title: str | None = None
) -> tuple[str, str]:
    """(What failed, what to do) for a source that can't be opened or read."""
    if camera_info is None:
        return QCoreApplication.translate("SourceBar", "The source can't be read."), ""
    name = source_full_name(camera_info, window_title)
    kind = camera_info.type
    if kind == CameraInfo.CameraType.FILE:
        return (
            QCoreApplication.translate(
                "SourceBar", "Can't play the video file {name}."
            ).format(name=file_name(camera_info.id)),
            QCoreApplication.translate(
                "SourceBar",
                "It may have been moved, be damaged or use a format that can't be "
                "read (MP4 and AVI work best).",
            ),
        )
    if kind == CameraInfo.CameraType.URL:
        return (
            QCoreApplication.translate(
                "SourceBar", "Can't open the stream {url}."
            ).format(url=name),
            QCoreApplication.translate(
                "SourceBar",
                "Check the address, the user name and password, and that the camera "
                "or server is on and reachable from this computer. A stream gets "
                "5 seconds to answer.",
            ),
        )
    if kind == CameraInfo.CameraType.SCREEN_CAPTURE:
        return (
            QCoreApplication.translate("SourceBar", "Can't capture {window}.").format(
                window=name
            ),
            QCoreApplication.translate(
                "SourceBar", "The window may have been closed or minimized."
            ),
        )
    if kind == CameraInfo.CameraType.PHONE:
        return (
            QCoreApplication.translate(
                "SourceBar", "Can't start the phone camera's page."
            ),
            QCoreApplication.translate(
                "SourceBar",
                "ScoreSight serves it over HTTPS on the port after the HTTP "
                "server's. The log says why it failed.",
            ),
        )
    if kind == CameraInfo.CameraType.NDI:
        return (
            QCoreApplication.translate(
                "SourceBar", "Can't receive the NDI source {name}."
            ).format(name=name),
            QCoreApplication.translate(
                "SourceBar",
                "Check that it is still on the network, then Retry or reload the "
                "sources.",
            ),
        )
    return (
        QCoreApplication.translate("SourceBar", "Can't open {name}.").format(name=name),
        QCoreApplication.translate(
            "SourceBar",
            "It may be unplugged or used by another program: close that program, "
            "then Retry.",
        ),
    )


def screen_recording_permission_text() -> tuple[str, str]:
    """(What's wrong, what to do) when macOS doesn't let ScoreSight record the
    screen: the capture then shows only the desktop."""
    return (
        QCoreApplication.translate(
            "SourceBar", "ScoreSight isn't allowed to record the screen."
        ),
        QCoreApplication.translate(
            "SourceBar",
            "macOS shows only the desktop to apps without the Screen Recording "
            "permission. Allow ScoreSight in System Settings, then restart it.",
        ),
    )


def screen_recording_allowed() -> bool | None:
    """Whether macOS lets this app record the screen: True or False on macOS
    10.15 and later, None where there's no such permission or it can't be
    told (CGPreflightScreenCaptureAccess doesn't ask the user)."""
    if platform.system() != "Darwin":
        return None
    try:
        import Quartz  # pyobjc, on macOS only

        preflight = getattr(Quartz, "CGPreflightScreenCaptureAccess", None)
        if preflight is None:
            return None
        return bool(preflight())
    except Exception:
        return None


def four_corner_banner_text(picked: int, has_correction: bool) -> str:
    """The four-corner picking banner: how many corners were clicked, and what
    Esc does."""
    text = QCoreApplication.translate(
        "SourceBar", "<b>Click the 4 corners of the scoreboard:</b> {picked} of 4."
    ).format(picked=picked)
    if has_correction:
        text += " " + QCoreApplication.translate(
            "SourceBar", "Esc cancels and keeps the previous correction."
        )
    else:
        text += " " + QCoreApplication.translate("SourceBar", "Esc cancels.")
    return text


def next_speed(speed) -> int:
    """The playback speed after speed (1, 2, 4 ... 32, then 1 again)."""
    try:
        index = PLAYBACK_SPEEDS.index(speed)
    except ValueError:
        return PLAYBACK_SPEEDS[0]
    return PLAYBACK_SPEEDS[(index + 1) % len(PLAYBACK_SPEEDS)]


def speed_text(speed) -> str:
    return f"×{speed}"


def zoom_text(scale: float) -> str:
    """The zoom readout: the size of an image pixel on screen, in percent."""
    return QCoreApplication.translate("MainWindow", "{zoom}%").format(
        zoom=round(scale * 100)
    )


def rotate_text(angle) -> str:
    """The Rotate button: what a click does, and the current angle."""
    return QCoreApplication.translate("MainWindow", "Rotate 90° · {angle}°").format(
        angle=int(angle or 0) % 360
    )


def quickstart_link() -> str:
    return '<a href="{url}">{text}</a> ↗'.format(
        url=QUICKSTART_URL,
        text=QCoreApplication.translate("MainWindow", "5-minute Quickstart"),
    )


def community_link() -> str:
    return '<a href="{url}">{text}</a> ↗'.format(
        url=COMMUNITY_URL,
        text=QCoreApplication.translate("MainWindow", "Questions? Ask the community"),
    )


class CompactToolRow(QObject):
    """Fits a row of controls into less room, in up to three steps:

    0. as designed;
    1. compact: its tool buttons show their icons only (their texts stay
       their tooltips and accessible names) and its labels hide;
    2. wrapped: also compact, and the widgets in wraps move to other cells of
       the row's grid layout, e.g. to a second line.

    The step is chosen from the room the row has (the width of area: the row
    itself, or e.g. the space a centred card can use) against the width each
    step needs. The row's minimum width is the last step's, so the window can
    always be as narrow as that.
    """

    WRAPPED = 2

    def __init__(
        self,
        row: QWidget,
        buttons=(),
        labels=(),
        wraps=(),
        area: QWidget | None = None,
        ignore=(),
        icon_buttons=(),
    ):
        """wraps: (widget, (row, column[, rowspan, colspan[, alignment]]) as
        designed, (...) wrapped) of the row's grid layout; ignore: widgets
        whose width isn't needed (they hide by themselves when there's no
        room); icon_buttons: buttons that also show their icon as designed
        (beside their text)."""
        super().__init__(row)
        self.row = row
        self.buttons = list(buttons) + list(icon_buttons)
        self.icon_buttons = list(icon_buttons)
        self.labels = list(labels)
        self.wraps = list(wraps)
        self.area = area if area is not None else row
        self.ignore = list(ignore)
        self.step = 0
        # the width that steps 0 and 1 need
        self.needs = [0, 0]
        self.area.installEventFilter(self)
        if self.area is not self.row:
            self.row.installEventFilter(self)
        self.refresh()

    @property
    def compact(self) -> bool:
        return self.step > 0

    @property
    def wrapped(self) -> bool:
        return self.step == self.WRAPPED

    def eventFilter(self, watched, event):
        kind = event.type()
        if watched is self.area and kind == QEvent.Type.Resize:
            self.update()
        elif kind in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            # the texts' widths changed
            self.refresh()
        return False

    def refresh(self):
        """Measure the steps again (after the texts changed, e.g. with the
        language, or the style)."""
        for step in (0, 1):
            self.apply(step)
            self.needs[step] = self.neededWidth()
        last = self.WRAPPED if self.wraps else 1
        self.apply(last)
        self.row.setMinimumWidth(0)
        self.activate()
        minimum = self.row.minimumSizeHint().width()
        # narrower than the earlier steps need: they squeeze until the next
        # resize picks the step that fits
        self.row.setMinimumWidth(minimum)
        self.update()

    def update(self):
        width = self.area.width()
        if width >= self.needs[0]:
            step = 0
        elif width >= self.needs[1] or not self.wraps:
            step = 1
        else:
            step = self.WRAPPED
        if step != self.step:
            self.apply(step)

    def activate(self):
        for widget in [self.row] + self.row.findChildren(QWidget):
            layout = widget.layout()
            if layout is not None:
                layout.invalidate()
                layout.activate()

    def neededWidth(self) -> int:
        self.activate()
        width = self.row.sizeHint().width()
        layout = self.row.layout()
        spacing = max(0, layout.spacing()) if layout is not None else 0
        for widget in self.ignore:
            if not widget.isHidden():
                width -= widget.sizeHint().width() + spacing
        return width

    def apply(self, step: int):
        self.step = step
        for button in self.buttons:
            if step > 0:
                style = Qt.ToolButtonStyle.ToolButtonIconOnly
            elif button in self.icon_buttons:
                style = Qt.ToolButtonStyle.ToolButtonTextBesideIcon
            else:
                style = Qt.ToolButtonStyle.ToolButtonTextOnly
            button.setToolButtonStyle(style)
        for label in self.labels:
            label.setVisible(step == 0)
        for widget, designed, wrapped in self.wraps:
            cell = wrapped if step == self.WRAPPED else designed
            layout = widget.parentWidget().layout()
            layout.removeWidget(widget)
            layout.addWidget(widget, *cell)
