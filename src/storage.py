import json
import os
import re
import shutil
import tempfile
import threading
import time
from collections.abc import Callable
from datetime import datetime

from PySide6.QtCore import QObject, Signal, QRectF
from platformdirs import user_data_dir
from defaults import (
    default_info_for_box_name,
    format_prefixes,
    normalize_settings_dict,
)

from text_detection_target import TextDetectionTarget
from sc_logging import logger

APP_NAME = "scoresight"
# The main settings file. With SCORESIGHT_PROFILE=<name> it maps to
# scoresight-<name>.json (see resolve_file_name).
SETTINGS_FILE = "scoresight.json"

# Serializes every read-modify-write of the JSON files in this process. It is
# re-entrant so a helper that does fetch + store can hold it across both calls.
_storage_lock = threading.RLock()

# {logical file name: {document name: [callbacks]}}. Keyed by the logical file
# name the callers use (e.g. "scoresight.json"), not by the resolved absolute
# path, so subscriptions survive a change of data dir or profile.
data_subscribers: dict[str, dict[str, list[Callable]]] = {}

# Corrupt files that could not be moved aside, so they are not handled again on
# every read: {(path, size, mtime_ns): whether a backup copy exists}.
_reported_corrupt_files: dict[tuple[str, int, int], bool] = {}

_PROFILE_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]")

# Version of the stored box format, kept next to "boxes" in the settings file
# and in exported configuration files. Boxes without it (saved by ScoreSight
# 0.1.x) or with an older version are migrated once (see migrate_boxes).
BOXES_SCHEMA_KEY = "boxes_schema_version"
BOXES_SCHEMA_VERSION = 3

# Schema 3: the expressions of the Time 0-59 and Shotclock 0-39 format presets
# up to ScoreSight 0.3.0 (schema 2), which took exactly two digits -> the
# presets' expressions now (one or two digits).
TWO_DIGIT_FORMATS = {
    "^[0-5]\\d$": format_prefixes[4],
    "^[0-3]\\d$": format_prefixes[5],
}


def get_data_dir() -> str:
    """The user data directory. SCORESIGHT_DATA_DIR overrides the platform default."""
    override = os.environ.get("SCORESIGHT_DATA_DIR")
    if override:
        return os.path.abspath(os.path.expanduser(override))
    return user_data_dir(APP_NAME)


def get_profile() -> str | None:
    """The active configuration profile (SCORESIGHT_PROFILE), sanitized for use in
    a file name, or None for the default profile."""
    profile = os.environ.get("SCORESIGHT_PROFILE", "").strip()
    if not profile:
        return None
    return _PROFILE_UNSAFE_CHARS.sub("_", profile)


def resolve_file_name(file_path: str) -> str:
    """Map a logical storage file name to the file actually used on disk.

    With a profile active, "scoresight.json" becomes "scoresight-<profile>.json".
    Other names are returned unchanged.
    """
    profile = get_profile()
    if profile and file_path == SETTINGS_FILE:
        return f"{APP_NAME}-{profile}.json"
    return file_path


def get_storage_path(file_path: str) -> str:
    """Absolute path of a logical storage file inside the data directory."""
    return os.path.join(get_data_dir(), resolve_file_name(file_path))


class _CorruptFileError(Exception):
    pass


def _read_documents(path: str) -> dict:
    """Load the documents dict from path. A missing file is an empty dict.

    Raises _CorruptFileError if the file exists but isn't a JSON object.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            documents = json.load(f)
    except FileNotFoundError:
        return {}
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise _CorruptFileError(str(e)) from e
    if not isinstance(documents, dict):
        raise _CorruptFileError(
            f"expected a JSON object, found {type(documents).__name__}"
        )
    return documents


def _backup_corrupt_file(path: str, reason: str) -> bool:
    """Move a corrupt settings file aside as <name>.corrupt-<timestamp> so it is
    never silently overwritten, and log where it went.

    Returns False only if the file still exists and no backup could be made.
    """
    try:
        stat = os.stat(path)
    except OSError:
        return True
    signature = (path, stat.st_size, stat.st_mtime_ns)
    if signature in _reported_corrupt_files:
        return _reported_corrupt_files[signature]

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = f"{path}.corrupt-{timestamp}"
    counter = 1
    while os.path.exists(backup_path):
        backup_path = f"{path}.corrupt-{timestamp}-{counter}"
        counter += 1

    try:
        os.replace(path, backup_path)
    except OSError:
        # e.g. another process holds the file open on Windows: keep a copy and
        # let the next atomic write replace the corrupt file.
        try:
            shutil.copy2(path, backup_path)
        except OSError:
            logger.exception(
                "Settings file %s is corrupt (%s) and could not be backed up; "
                "it will not be overwritten.",
                path,
                reason,
            )
            _reported_corrupt_files[signature] = False
            return False
        _reported_corrupt_files[signature] = True
    logger.error(
        "Settings file %s is corrupt (%s). It was backed up to %s and settings "
        "start from defaults.",
        path,
        reason,
        backup_path,
    )
    return True


def _load_documents(path: str, for_write: bool = False) -> dict:
    """Read the documents dict, backing up (never discarding) a corrupt file.

    With for_write, raises OSError if the file is corrupt and could not be backed
    up, so the caller doesn't overwrite it. Must be called with _storage_lock held.
    """
    try:
        return _read_documents(path)
    except _CorruptFileError as e:
        backed_up = _backup_corrupt_file(path, str(e))
        if for_write and not backed_up:
            raise OSError(
                f"Refusing to overwrite corrupt settings file {path}: "
                "it could not be backed up"
            ) from e
        return {}


def _replace_with_retry(src: str, dst: str, attempts: int = 10, delay: float = 0.05):
    # On Windows os.replace fails with PermissionError while another process
    # (antivirus, indexer, an editor) briefly has the destination open.
    for attempt in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay)


def write_json_atomic(path: str, data, indent: int = 2):
    """Write data as JSON to path atomically: a temp file in the same directory is
    written, flushed and fsynced, then moved over path. A crash at any point
    leaves either the old file or the new one, never a truncated file."""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=os.path.basename(path) + ".", suffix=".tmp", dir=directory
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent)
            f.flush()
            os.fsync(f.fileno())
        _replace_with_retry(tmp_path, path)
    except BaseException:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def _notify_subscribers(file_path: str, document_name: str, data):
    with _storage_lock:
        callbacks = list(data_subscribers.get(file_path, {}).get(document_name, []))
    # Called outside the lock: a subscriber may block (e.g. reopen a camera) or
    # store other data. A failing subscriber must not affect the others.
    for callback in callbacks:
        try:
            callback(data)
        except Exception:
            logger.exception(
                "Subscriber %r for '%s' in %s failed",
                callback,
                document_name,
                file_path,
            )


def subscribe_to_data(file_path: str, document_name: str, callback: Callable):
    """Call callback(data) after document_name in file_path is stored, or
    callback(None) after it is removed. Callbacks run synchronously on the thread
    that stores the data. Subscribing the same callback twice has no effect."""
    with _storage_lock:
        callbacks = data_subscribers.setdefault(file_path, {}).setdefault(
            document_name, []
        )
        if callback not in callbacks:
            callbacks.append(callback)


def unsubscribe_from_data(file_path: str, document_name: str, callback: Callable):
    """Remove a callback registered with subscribe_to_data. Returns True if it was
    subscribed."""
    with _storage_lock:
        documents = data_subscribers.get(file_path)
        if not documents or document_name not in documents:
            return False
        callbacks = documents[document_name]
        if callback not in callbacks:
            return False
        callbacks.remove(callback)
        if not callbacks:
            del documents[document_name]
        if not documents:
            del data_subscribers[file_path]
        return True


def clear_subscribers():
    """Remove all subscriptions (used by tests)."""
    with _storage_lock:
        data_subscribers.clear()


def store_data(file_path: str, document_name: str, data):
    """Store data as document_name in file_path (relative to the data dir), then
    notify the document's subscribers. The write is atomic; a corrupt existing
    file is backed up rather than overwritten."""
    path = get_storage_path(file_path)
    with _storage_lock:
        documents = _load_documents(path, for_write=True)
        documents[document_name] = data
        write_json_atomic(path, documents)
    _notify_subscribers(file_path, document_name, data)


def remove_data(file_path: str, document_name: str):
    """Remove document_name from file_path, then notify its subscribers with None."""
    path = get_storage_path(file_path)
    with _storage_lock:
        if not os.path.exists(path):
            return
        documents = _load_documents(path, for_write=True)
        documents.pop(document_name, None)
        write_json_atomic(path, documents)
    _notify_subscribers(file_path, document_name, None)


def fetch_data(file_path: str, document_name: str, default=None):
    """Return document_name from file_path, or default if it (or the file) is
    missing or the file is corrupt."""
    path = get_storage_path(file_path)
    with _storage_lock:
        documents = _load_documents(path)
    return documents.get(document_name, default)


def store_custom_box_name(custom_box_name: str):
    with _storage_lock:
        # get the current custom box names
        custom_boxes_names = fetch_data(SETTINGS_FILE, "custom_boxes_names", [])
        if custom_box_name in custom_boxes_names:
            return
        custom_boxes_names.append(custom_box_name)
        # Store the custom box name in the scoresight.json file
        store_data(SETTINGS_FILE, "custom_boxes_names", custom_boxes_names)


def rename_custom_box_name_in_storage(old_name: str, new_name: str):
    with _storage_lock:
        # get the current custom box names
        custom_boxes_names = fetch_data(SETTINGS_FILE, "custom_boxes_names", [])
        if old_name in custom_boxes_names:
            custom_boxes_names.remove(old_name)
        custom_boxes_names.append(new_name)
        # Store the custom box name in the scoresight.json file
        store_data(SETTINGS_FILE, "custom_boxes_names", custom_boxes_names)


def remove_custom_box_name_in_storage(custom_box_name: str):
    with _storage_lock:
        # get the current custom box names
        custom_boxes_names = fetch_data(SETTINGS_FILE, "custom_boxes_names", [])
        if custom_box_name in custom_boxes_names:
            custom_boxes_names.remove(custom_box_name)
        # Store the custom box name in the scoresight.json file
        store_data(SETTINGS_FILE, "custom_boxes_names", custom_boxes_names)


def fetch_custom_box_names():
    return fetch_data(SETTINGS_FILE, "custom_boxes_names", [])


def boxes_need_migration(schema_version) -> bool:
    """Whether boxes stored with schema_version (None: no marker, ScoreSight
    0.1.x) must go through migrate_boxes."""
    return not isinstance(schema_version, int) or schema_version < BOXES_SCHEMA_VERSION


def migrate_boxes(boxes: list, origin: str, schema_version=None) -> list:
    """Bring boxes stored with schema_version (None: no marker, ScoreSight
    0.1.x) up to BOXES_SCHEMA_VERSION.

    Schema 2: the confidence threshold (conf_thresh) was never applied before
    0.2.0 (it was compared on the wrong scale), so every box carries the old
    0.5 default that did nothing. Applying it now would reject many correct
    readings, so it is reset to 0 (off), which keeps the old behavior.
    Schema 3: the Time 0-59 and Shotclock 0-39 format presets took exactly two
    digits up to 0.3.0, so a clock that shows 9 rather than 09 failed the
    filter. A format that is one of those old expressions becomes the preset's
    new one (TWO_DIGIT_FORMATS); any other format is kept.
    Returns migrated copies; origin names where the boxes came from, for the log.
    Malformed entries are left for loadBoxesFromDict to reject.
    """
    if not isinstance(schema_version, int):
        schema_version = 1
    migrated = []
    formats_updated = 0
    for box in boxes:
        if isinstance(box, dict):
            settings = box.get("settings")
            settings = dict(settings) if isinstance(settings, dict) else {}
            changed = False
            if schema_version < 2:
                settings["conf_thresh"] = 0.0
                changed = True
            old_format = settings.get("format_regex")
            if (
                schema_version < 3
                and isinstance(old_format, str)
                and old_format in TWO_DIGIT_FORMATS
            ):
                settings["format_regex"] = TWO_DIGIT_FORMATS[old_format]
                formats_updated += 1
                changed = True
            if changed:
                box = {**box, "settings": settings}
        migrated.append(box)
    if schema_version < 2 and migrated:
        logger.info(
            "Migrated %d box(es) from %s, saved by an older ScoreSight: their "
            "confidence threshold had no effect before 0.2.0 and is now off (0); "
            "set Conf. Th per box to use it",
            len(migrated),
            origin,
        )
    if formats_updated:
        logger.info(
            "Migrated the format of %d box(es) from %s, saved by an older "
            "ScoreSight: Time 0-59 and Shotclock 0-39 now also accept a single "
            "digit (9 as well as 09)",
            formats_updated,
            origin,
        )
    return migrated


class TextDetectionTargetMemoryStorage(QObject):
    # This class is used to store the text detection targets in memory

    _instance = None
    data_changed = Signal(list)

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(TextDetectionTargetMemoryStorage, cls).__new__(
                cls, *args, **kwargs
            )
        return cls._instance

    def __init__(self):
        if not hasattr(self, "_initialized"):
            super().__init__()
            self._data: list[TextDetectionTarget] = []
            self._initialized = True

    def add_item(self, item: TextDetectionTarget):
        self._data.append(item)
        self.data_changed.emit(self._data)

    def remove_item(self, item_name: str):
        for i, item in enumerate(self._data):
            if item.name == item_name:
                del self._data[i]
                break
        self.data_changed.emit(self._data)

    def clear(self):
        self._data.clear()
        self.data_changed.emit(self._data)

    def edit_item(self, item_name: str, new_item: TextDetectionTarget):
        for i, item in enumerate(self._data):
            if item.name == item_name:
                self._data[i].setRect(
                    new_item.x(), new_item.y(), new_item.width(), new_item.height()
                )
                self._data[i].settings = new_item.settings
                self.data_changed.emit(self._data)
                return
        logger.warning("unable to find item to edit in storage: " + item_name)

    def move_items(self, dx: float, dy: float):
        """Move every box (not the template fields, which have none) by
        (dx, dy) pixels, e.g. to keep them on the same part of the picture
        when the crop changes; one data_changed for all of them."""
        moved = False
        for item in self._data:
            if not (item.settings or {}).get("templatefield"):
                item.translate(dx, dy)
                moved = True
        if moved:
            self.data_changed.emit(self._data)

    def rename_item(self, old_name: str, new_name: str):
        for i, item in enumerate(self._data):
            if item.name == old_name:
                self._data[i].name = new_name
                self.data_changed.emit(self._data)
                return True
        logger.warning("unable to find item to rename in storage: " + old_name)
        return False

    def get_data(self):
        return self._data

    def is_empty(self):
        return len(self._data) == 0

    def find_item_by_name(self, name: str):
        for item in self._data:
            if item.name == name:
                return item
        return None

    def loadBoxesFromStorage(self) -> bool:
        """Load the boxes from the settings file. Boxes saved by an older
        version are migrated, and saved back once with the schema version."""
        boxes = fetch_data(SETTINGS_FILE, "boxes")
        if not boxes:
            return False
        schema_version = fetch_data(SETTINGS_FILE, BOXES_SCHEMA_KEY)
        migrate = boxes_need_migration(schema_version)
        if migrate:
            boxes = migrate_boxes(
                boxes,
                f"the settings file {resolve_file_name(SETTINGS_FILE)}",
                schema_version,
            )
        if not self.loadBoxesFromDict(boxes):
            return False
        if migrate:
            self.saveBoxesToStorage()
        return True

    def loadBoxesFromFile(self, file_path) -> bool:
        """Load the boxes from an exported configuration file: a
        {"boxes_schema_version": N, "boxes": [...]} object, or a plain list of
        boxes (exported by ScoreSight 0.1.x). Boxes of an older schema are
        migrated."""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            logger.error("Cannot read the configuration file %s: %s", file_path, e)
            return False
        if isinstance(data, list):
            boxes, schema_version = data, None
        elif isinstance(data, dict) and isinstance(data.get("boxes"), list):
            boxes, schema_version = data["boxes"], data.get(BOXES_SCHEMA_KEY)
        else:
            logger.error("%s is not a ScoreSight configuration file", file_path)
            return False
        if boxes_need_migration(schema_version):
            boxes = migrate_boxes(
                boxes, f"the configuration file {file_path}", schema_version
            )
        return self.loadBoxesFromDict(boxes)

    def loadBoxesFromDict(self, boxes) -> bool:
        data_backup = self._data.copy()
        self._data.clear()
        try:
            for box in boxes:
                logger.debug("loading box: " + box["name"])
                if "settings" not in box:
                    box["settings"] = {}

                default_box_info = default_info_for_box_name(box["name"])
                mini_rects: list[QRectF] = []
                if "mini_rects" in box:
                    for mini_rect in box["mini_rects"]:
                        mini_rects.append(
                            QRectF(
                                mini_rect["x"],
                                mini_rect["y"],
                                mini_rect["width"],
                                mini_rect["height"],
                            )
                        )
                # set the position of the box
                self._data.append(
                    TextDetectionTarget(
                        box["rect"]["x"],
                        box["rect"]["y"],
                        box["rect"]["width"],
                        box["rect"]["height"],
                        box["name"],
                        normalize_settings_dict(box["settings"], default_box_info),
                        mini_rects,
                    )
                )
                if "is_custom" in box["settings"] and box["settings"]["is_custom"]:
                    store_custom_box_name(box["name"])
            logger.debug("loaded boxes")
            self.data_changed.emit(self._data)
        except Exception as e:
            logger.error("error loading boxes: " + str(e))
            self._data = data_backup
            return False
        return True

    def getBoxesForStorage(self) -> list[dict]:
        # save all the boxes to scoresight.json
        boxes = []
        for detectionTarget in self._data:
            # normalize_settings_dict returns exactly the canonical, persisted
            # per-box settings (runtime-only keys such as median_wh_ratio are not
            # included), so serializing its whole output means a new setting can't
            # be forgotten here.
            detectionTarget.settings = normalize_settings_dict(
                detectionTarget.settings,
                default_info_for_box_name(detectionTarget.name),
            )
            boxes.append(
                {
                    "name": detectionTarget.name,
                    "rect": {
                        "x": detectionTarget.x(),
                        "y": detectionTarget.y(),
                        "width": detectionTarget.width(),
                        "height": detectionTarget.height(),
                    },
                    "settings": dict(detectionTarget.settings),
                    "mini_rects": [
                        {
                            "x": mini_rect.x(),
                            "y": mini_rect.y(),
                            "width": mini_rect.width(),
                            "height": mini_rect.height(),
                        }
                        for mini_rect in detectionTarget.mini_rects
                    ],
                }
            )
        return boxes

    def saveBoxesToFile(self, file_path):
        boxes = self.getBoxesForStorage()
        write_json_atomic(
            file_path, {BOXES_SCHEMA_KEY: BOXES_SCHEMA_VERSION, "boxes": boxes}
        )

    def saveBoxesToStorage(self):
        boxes = self.getBoxesForStorage()
        with _storage_lock:
            store_data(SETTINGS_FILE, "boxes", boxes)
            # The marker is written after the boxes: an interrupted save can
            # leave migrated boxes unmarked (migrated again, harmlessly), but
            # never marks boxes that weren't migrated.
            if fetch_data(SETTINGS_FILE, BOXES_SCHEMA_KEY) != BOXES_SCHEMA_VERSION:
                store_data(SETTINGS_FILE, BOXES_SCHEMA_KEY, BOXES_SCHEMA_VERSION)
