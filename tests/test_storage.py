import json
import os
import threading

import pytest

import storage
from defaults import FieldType, format_prefixes, normalize_settings_dict
from storage import (
    fetch_custom_box_names,
    fetch_data,
    remove_custom_box_name_in_storage,
    remove_data,
    rename_custom_box_name_in_storage,
    store_custom_box_name,
    store_data,
    subscribe_to_data,
    unsubscribe_from_data,
)
from text_detection_target import TextDetectionTarget

SETTINGS = "scoresight.json"


def read_settings_file(data_dir, name=SETTINGS):
    with open(data_dir / name, encoding="utf-8") as f:
        return json.load(f)


def leftover_temp_files(directory):
    return [name for name in os.listdir(directory) if name.endswith(".tmp")]


# --- store / fetch / remove -------------------------------------------------


def test_store_and_fetch_roundtrip(data_dir):
    store_data(SETTINGS, "number", 3)
    store_data(SETTINGS, "nested", {"a": [1, 2, {"b": None}], "s": "Ünïcode ✓"})

    assert fetch_data(SETTINGS, "number") == 3
    assert fetch_data(SETTINGS, "nested") == {
        "a": [1, 2, {"b": None}],
        "s": "Ünïcode ✓",
    }
    assert read_settings_file(data_dir) == {
        "number": 3,
        "nested": {"a": [1, 2, {"b": None}], "s": "Ünïcode ✓"},
    }


def test_store_overwrites_and_keeps_other_documents(data_dir):
    store_data(SETTINGS, "a", 1)
    store_data(SETTINGS, "b", 2)
    store_data(SETTINGS, "a", "one")
    assert read_settings_file(data_dir) == {"a": "one", "b": 2}


def test_store_creates_missing_data_dir(data_dir):
    assert not data_dir.exists()
    store_data(SETTINGS, "x", True)
    assert (data_dir / SETTINGS).is_file()


def test_fetch_defaults(data_dir):
    # no file yet
    assert fetch_data(SETTINGS, "missing") is None
    assert fetch_data(SETTINGS, "missing", 42) == 42
    store_data(SETTINGS, "present", 0)
    # file exists, document doesn't
    assert fetch_data(SETTINGS, "missing", "dflt") == "dflt"
    # falsy stored values are returned, not replaced by the default
    assert fetch_data(SETTINGS, "present", 99) == 0


def test_fetch_returns_independent_copies(data_dir):
    store_data(SETTINGS, "list", [1, 2])
    fetch_data(SETTINGS, "list").append(3)
    assert fetch_data(SETTINGS, "list") == [1, 2]


def test_remove_data(data_dir):
    store_data(SETTINGS, "a", 1)
    store_data(SETTINGS, "b", 2)
    remove_data(SETTINGS, "a")
    assert fetch_data(SETTINGS, "a", "gone") == "gone"
    assert read_settings_file(data_dir) == {"b": 2}
    # removing a missing document or from a missing file is a no-op
    remove_data(SETTINGS, "never-stored")
    remove_data("other.json", "a")
    assert not (data_dir / "other.json").exists()


def test_get_data_dir_honours_env(data_dir, monkeypatch, tmp_path):
    assert storage.get_data_dir() == str(data_dir)
    monkeypatch.setenv("SCORESIGHT_DATA_DIR", str(tmp_path / "elsewhere"))
    store_data(SETTINGS, "x", 1)
    assert (tmp_path / "elsewhere" / SETTINGS).is_file()
    assert not (data_dir / SETTINGS).exists()


# --- subscribers --------------------------------------------------------------


def test_subscriber_receives_stored_and_removed_values(data_dir):
    received = []
    subscribe_to_data(SETTINGS, "doc", received.append)
    store_data(SETTINGS, "doc", {"v": 1})
    store_data(SETTINGS, "other-doc", "ignored")
    remove_data(SETTINGS, "doc")
    assert received == [{"v": 1}, None]


def test_subscriber_is_notified_after_the_write(data_dir):
    seen_on_disk = []

    def callback(value):
        # the value must already be persisted when subscribers run
        seen_on_disk.append(read_settings_file(data_dir).get("doc"))

    subscribe_to_data(SETTINGS, "doc", callback)
    store_data(SETTINGS, "doc", "v1")
    store_data(SETTINGS, "doc", "v2")
    assert seen_on_disk == ["v1", "v2"]


def test_unsubscribe(data_dir):
    received = []
    subscribe_to_data(SETTINGS, "doc", received.append)
    store_data(SETTINGS, "doc", 1)
    assert unsubscribe_from_data(SETTINGS, "doc", received.append) is True
    store_data(SETTINGS, "doc", 2)
    assert received == [1]
    # unsubscribing again, or something never subscribed, reports False
    assert unsubscribe_from_data(SETTINGS, "doc", received.append) is False
    assert unsubscribe_from_data(SETTINGS, "nope", print) is False
    assert storage.data_subscribers == {}


def test_unsubscribe_bound_method_and_keep_others(data_dir):
    class Component:
        def __init__(self):
            self.values = []

        def on_change(self, value):
            self.values.append(value)

    first, second = Component(), Component()
    subscribe_to_data(SETTINGS, "doc", first.on_change)
    subscribe_to_data(SETTINGS, "doc", second.on_change)
    # a fresh bound-method object for the same instance unsubscribes it
    assert unsubscribe_from_data(SETTINGS, "doc", first.on_change)
    store_data(SETTINGS, "doc", "x")
    assert first.values == []
    assert second.values == ["x"]


def test_subscribing_twice_notifies_once(data_dir):
    received = []
    subscribe_to_data(SETTINGS, "doc", received.append)
    subscribe_to_data(SETTINGS, "doc", received.append)
    store_data(SETTINGS, "doc", 1)
    assert received == [1]


def test_raising_subscriber_does_not_block_persistence_or_others(data_dir, caplog):
    received = []

    def broken(value):
        raise RuntimeError("subscriber bug")

    subscribe_to_data(SETTINGS, "doc", broken)
    subscribe_to_data(SETTINGS, "doc", received.append)
    store_data(SETTINGS, "doc", 7)  # must not raise

    assert fetch_data(SETTINGS, "doc") == 7
    assert received == [7]
    assert any("subscriber bug" in (r.exc_text or "") for r in caplog.records) or any(
        r.exc_info and "subscriber bug" in str(r.exc_info[1]) for r in caplog.records
    )


def test_subscriber_may_store_and_unsubscribe_reentrantly(data_dir):
    calls = []

    def callback(value):
        calls.append(value)
        unsubscribe_from_data(SETTINGS, "doc", callback)
        store_data(SETTINGS, "derived", value * 2)

    subscribe_to_data(SETTINGS, "doc", callback)
    store_data(SETTINGS, "doc", 5)
    store_data(SETTINGS, "doc", 6)
    assert calls == [5]
    assert fetch_data(SETTINGS, "derived") == 10


def test_subscriptions_survive_data_dir_and_profile_changes(
    data_dir, monkeypatch, tmp_path
):
    received = []
    subscribe_to_data(SETTINGS, "doc", received.append)
    monkeypatch.setenv("SCORESIGHT_DATA_DIR", str(tmp_path / "moved"))
    store_data(SETTINGS, "doc", 1)
    monkeypatch.setenv("SCORESIGHT_PROFILE", "studio")
    store_data(SETTINGS, "doc", 2)
    assert received == [1, 2]


# --- corrupt files -----------------------------------------------------------


def corrupt_backups(data_dir, name=SETTINGS):
    return sorted(p for p in os.listdir(data_dir) if p.startswith(f"{name}.corrupt-"))


@pytest.mark.parametrize(
    "content",
    [b"", b'{"boxes": [1, 2', b"not json at all", b"[1, 2, 3]", b"null", b"\xff\xfe"],
    ids=["empty", "truncated", "garbage", "list", "null", "binary"],
)
def test_corrupt_file_is_backed_up_not_wiped(data_dir, content):
    data_dir.mkdir()
    (data_dir / SETTINGS).write_bytes(content)

    # reads fall back to the default
    assert fetch_data(SETTINGS, "boxes", "default") == "default"

    store_data(SETTINGS, "new", 1)
    assert read_settings_file(data_dir) == {"new": 1}

    backups = corrupt_backups(data_dir)
    assert len(backups) == 1
    # the original bytes are preserved in the backup
    assert (data_dir / backups[0]).read_bytes() == content


def test_corrupt_file_logged(data_dir, caplog):
    data_dir.mkdir()
    (data_dir / SETTINGS).write_text("{oops", encoding="utf-8")
    store_data(SETTINGS, "a", 1)
    assert any(
        "corrupt" in r.getMessage() and r.levelname == "ERROR" for r in caplog.records
    )


def test_remove_data_on_corrupt_file_does_not_raise(data_dir):
    data_dir.mkdir()
    (data_dir / SETTINGS).write_text("{oops", encoding="utf-8")
    remove_data(SETTINGS, "anything")
    assert len(corrupt_backups(data_dir)) == 1
    assert read_settings_file(data_dir) == {}


def test_corrupt_file_that_cannot_be_moved_is_copied(data_dir, monkeypatch):
    data_dir.mkdir()
    settings_path = data_dir / SETTINGS
    settings_path.write_text("{oops", encoding="utf-8")
    real_replace = os.replace

    def replace(src, dst):
        if ".corrupt-" in str(dst):
            raise PermissionError("file is open in another process")
        return real_replace(src, dst)

    monkeypatch.setattr(storage.os, "replace", replace)
    store_data(SETTINGS, "a", 1)

    backups = corrupt_backups(data_dir)
    assert len(backups) == 1
    assert (data_dir / backups[0]).read_text(encoding="utf-8") == "{oops"
    assert read_settings_file(data_dir) == {"a": 1}


def test_corrupt_file_that_cannot_be_backed_up_is_not_overwritten(
    data_dir, monkeypatch
):
    data_dir.mkdir()
    settings_path = data_dir / SETTINGS
    settings_path.write_text("{oops", encoding="utf-8")
    monkeypatch.setattr(storage, "_backup_corrupt_file", lambda path, reason: False)

    with pytest.raises(OSError):
        store_data(SETTINGS, "a", 1)
    with pytest.raises(OSError):
        remove_data(SETTINGS, "a")
    assert settings_path.read_text(encoding="utf-8") == "{oops"
    # reads still work (with defaults)
    assert fetch_data(SETTINGS, "a", "dflt") == "dflt"


def test_repeated_reads_of_corrupt_file_make_one_backup(data_dir):
    data_dir.mkdir()
    (data_dir / SETTINGS).write_text("{oops", encoding="utf-8")
    for _ in range(5):
        assert fetch_data(SETTINGS, "a") is None
    assert len(corrupt_backups(data_dir)) == 1


# --- atomicity and concurrency -------------------------------------------------


def test_failed_serialization_leaves_file_intact(data_dir):
    store_data(SETTINGS, "keep", "me")
    before = (data_dir / SETTINGS).read_bytes()

    with pytest.raises(TypeError):
        store_data(SETTINGS, "bad", object())

    assert (data_dir / SETTINGS).read_bytes() == before
    assert leftover_temp_files(data_dir) == []


def test_crash_before_replace_leaves_file_intact(data_dir, monkeypatch):
    store_data(SETTINGS, "keep", "me")
    before = (data_dir / SETTINGS).read_bytes()
    received = []
    subscribe_to_data(SETTINGS, "new", received.append)

    def crash(src, dst, *args, **kwargs):
        raise OSError("disk unplugged")

    monkeypatch.setattr(storage, "_replace_with_retry", crash)
    with pytest.raises(OSError):
        store_data(SETTINGS, "new", 1)

    assert (data_dir / SETTINGS).read_bytes() == before
    assert leftover_temp_files(data_dir) == []
    # subscribers are only notified after a successful write
    assert received == []


def test_write_goes_through_temp_file_in_same_directory(data_dir, monkeypatch):
    replaced = []
    real_replace = os.replace

    def replace(src, dst):
        replaced.append((os.path.dirname(src), os.path.basename(dst)))
        return real_replace(src, dst)

    monkeypatch.setattr(storage.os, "replace", replace)
    store_data(SETTINGS, "a", 1)
    assert replaced == [(str(data_dir), SETTINGS)]


def test_replace_is_retried_on_permission_error(data_dir, monkeypatch):
    real_replace = os.replace
    failures = {"left": 3}

    def flaky_replace(src, dst):
        if failures["left"]:
            failures["left"] -= 1
            raise PermissionError("sharing violation")
        return real_replace(src, dst)

    monkeypatch.setattr(storage.os, "replace", flaky_replace)
    monkeypatch.setattr(storage.time, "sleep", lambda seconds: None)
    store_data(SETTINGS, "a", 1)
    assert read_settings_file(data_dir) == {"a": 1}


def test_concurrent_stores_do_not_lose_updates(data_dir):
    threads_count, per_thread = 8, 20
    errors = []

    def worker(thread_index):
        try:
            for i in range(per_thread):
                store_data(SETTINGS, f"t{thread_index}-{i}", i)
                fetch_data(SETTINGS, f"t{thread_index}-{i}")
        except Exception as e:  # pragma: no cover - reported below
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(threads_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    documents = read_settings_file(data_dir)
    assert len(documents) == threads_count * per_thread
    assert leftover_temp_files(data_dir) == []


# --- profiles ----------------------------------------------------------------------


def test_profile_maps_settings_file(data_dir, monkeypatch):
    store_data(SETTINGS, "where", "default")
    monkeypatch.setenv("SCORESIGHT_PROFILE", "court2")

    assert storage.resolve_file_name(SETTINGS) == "scoresight-court2.json"
    assert fetch_data(SETTINGS, "where") is None
    store_data(SETTINGS, "where", "court2")
    remove_data(SETTINGS, "missing")

    assert read_settings_file(data_dir, "scoresight-court2.json") == {"where": "court2"}
    assert read_settings_file(data_dir) == {"where": "default"}

    monkeypatch.delenv("SCORESIGHT_PROFILE")
    assert fetch_data(SETTINGS, "where") == "default"


@pytest.mark.parametrize(
    ("profile", "expected"),
    [
        ("", SETTINGS),
        ("   ", SETTINGS),
        ("studio", "scoresight-studio.json"),
        (" Studio_B-2.1 ", "scoresight-Studio_B-2.1.json"),
        ("../../evil", "scoresight-.._.._evil.json"),
        ("a/b\\c:d", "scoresight-a_b_c_d.json"),
    ],
)
def test_profile_file_names(monkeypatch, profile, expected):
    monkeypatch.setenv("SCORESIGHT_PROFILE", profile)
    assert storage.resolve_file_name(SETTINGS) == expected
    # the mapped name is always a plain file inside the data dir
    assert os.path.dirname(storage.get_storage_path(SETTINGS)) == (
        storage.get_data_dir()
    )


def test_profile_only_maps_main_settings_file(monkeypatch):
    monkeypatch.setenv("SCORESIGHT_PROFILE", "studio")
    assert storage.resolve_file_name("other.json") == "other.json"


# --- custom box names --------------------------------------------------------------


def test_custom_box_names(data_dir):
    assert fetch_custom_box_names() == []
    store_custom_box_name("Custom 1")
    store_custom_box_name("Custom 2")
    store_custom_box_name("Custom 1")
    assert fetch_custom_box_names() == ["Custom 1", "Custom 2"]
    rename_custom_box_name_in_storage("Custom 1", "Team A")
    assert fetch_custom_box_names() == ["Custom 2", "Team A"]
    remove_custom_box_name_in_storage("Custom 2")
    remove_custom_box_name_in_storage("not there")
    assert fetch_custom_box_names() == ["Team A"]


# --- boxes (TextDetectionTargetMemoryStorage) --------------------------------------


def make_box(name, rect, **settings):
    from defaults import default_info_for_box_name

    return TextDetectionTarget(
        *rect,
        name,
        normalize_settings_dict(settings, default_info_for_box_name(name)),
        [],
    )


def test_serialized_settings_keys_match_normalize_settings(memory_storage):
    memory_storage.add_item(make_box("Home Score", (1, 2, 3, 4)))
    memory_storage.add_item(make_box("Custom 1", (5, 6, 7, 8)))
    canonical_keys = set(normalize_settings_dict({}, None))
    for box in memory_storage.getBoxesForStorage():
        assert set(box["settings"]) == canonical_keys


def test_box_roundtrip_through_settings_file(data_dir, memory_storage):
    from PySide6.QtCore import QRectF

    team_name = make_box(
        "Custom 1",
        (10.5, 20, 300, 40),
        type=FieldType.TEXT,
        format_regex="^[A-Z ]+$",
        conf_thresh=0.8,
        dilate=0,
        binarization_method=2,
        smoothing=True,
    )
    team_name.mini_rects = [QRectF(1, 2, 3, 4)]
    clock = make_box("Time", (0, 0, 170, 100), type=FieldType.TIME)
    # a runtime-only value that must not be persisted
    clock.settings["median_wh_ratio"] = 0.42
    memory_storage.add_item(team_name)
    memory_storage.add_item(clock)

    memory_storage.saveBoxesToStorage()
    saved = fetch_data(SETTINGS, "boxes")
    assert [b["name"] for b in saved] == ["Custom 1", "Time"]
    assert "median_wh_ratio" not in saved[1]["settings"]

    memory_storage.clear()
    changes = []
    memory_storage.data_changed.connect(changes.append)
    assert memory_storage.loadBoxesFromStorage() is True
    assert len(changes) == 1

    loaded = {box.name: box for box in memory_storage.get_data()}
    custom = loaded["Custom 1"]
    assert (custom.x(), custom.y(), custom.width(), custom.height()) == (
        10.5,
        20,
        300,
        40,
    )
    # the field type used to be dropped on save (Text/Time reverted to Number)
    assert custom.settings["type"] == FieldType.TEXT
    assert custom.settings["format_regex"] == "^[A-Z ]+$"
    assert custom.settings["conf_thresh"] == 0.8
    assert custom.settings["dilate"] == 0
    assert custom.settings["binarization_method"] == 2
    assert custom.settings["smoothing"] is True
    assert custom.settings["is_custom"] is True
    assert [(r.x(), r.y(), r.width(), r.height()) for r in custom.mini_rects] == [
        (1, 2, 3, 4)
    ]
    assert loaded["Time"].settings["type"] == FieldType.TIME
    assert loaded["Time"].settings["is_custom"] is False
    # loading a custom box registers its name
    assert "Custom 1" in fetch_custom_box_names()


def test_box_roundtrip_through_exported_file(tmp_path, memory_storage):
    memory_storage.add_item(make_box("Period", (1, 1, 50, 80), type=FieldType.TEXT))
    export = tmp_path / "exported config.json"
    memory_storage.saveBoxesToFile(str(export))
    assert leftover_temp_files(tmp_path) == []

    memory_storage.clear()
    assert memory_storage.loadBoxesFromFile(str(export)) is True
    [period] = memory_storage.get_data()
    assert period.settings["type"] == FieldType.TEXT
    # defaults that come from the predefined box info survive too
    assert period.settings["ordinal_indicator"] is True


def test_load_old_settings_without_type_uses_box_default(memory_storage):
    old_format = [
        {
            "name": "Time",
            "rect": {"x": 0, "y": 0, "width": 10, "height": 10},
            "settings": {"is_custom": False, "dilate": 2},
        }
    ]
    assert memory_storage.loadBoxesFromDict(old_format) is True
    [box] = memory_storage.get_data()
    assert box.settings["type"] == FieldType.TIME
    assert box.settings["dilate"] == 2


def test_invalid_boxes_keep_previous_boxes(memory_storage):
    memory_storage.add_item(make_box("Home Score", (1, 2, 3, 4)))
    assert memory_storage.loadBoxesFromDict([{"name": "No rect"}]) is False
    assert [box.name for box in memory_storage.get_data()] == ["Home Score"]


def test_load_from_empty_storage(memory_storage):
    assert memory_storage.loadBoxesFromStorage() is False
    assert memory_storage.is_empty()


# --- box schema migration -----------------------------------------------------


def old_box(name, conf_thresh, **settings):
    """A box as ScoreSight 0.1.x saved it."""
    return {
        "name": name,
        "rect": {"x": 1, "y": 2, "width": 30, "height": 40},
        "settings": {"conf_thresh": conf_thresh, **settings},
    }


def conf_thresholds(memory_storage):
    return {box.name: box.settings["conf_thresh"] for box in memory_storage.get_data()}


def formats(memory_storage):
    return {box.name: box.settings["format_regex"] for box in memory_storage.get_data()}


# the Shotclock 0-39 and Time 0-59 presets' expressions up to 0.3.0 (schema 2)
OLD_SHOT_CLOCK = "^[0-3]\\d$"
OLD_TIME_0_59 = "^[0-5]\\d$"


def test_new_boxes_have_the_confidence_threshold_off():
    assert normalize_settings_dict({}, None)["conf_thresh"] == 0.0


def test_boxes_from_0_1_x_get_the_confidence_threshold_off_once(
    data_dir, memory_storage, caplog
):
    # 0.1.x compared the 0-1 threshold with Tesseract's 0-100 confidence, so
    # it never rejected anything; applied now, the stored 0.5 default would
    # reject many good readings.
    store_data(
        SETTINGS, "boxes", [old_box("Home Score", 0.5), old_box("Time", 0.8, dilate=2)]
    )
    assert memory_storage.loadBoxesFromStorage() is True
    assert conf_thresholds(memory_storage) == {"Home Score": 0.0, "Time": 0.0}
    assert memory_storage.find_item_by_name("Time").settings["dilate"] == 2
    assert "Migrated 2 box(es)" in caplog.text
    # saved back once, with the schema version
    assert (
        fetch_data(SETTINGS, storage.BOXES_SCHEMA_KEY) == storage.BOXES_SCHEMA_VERSION
    )
    saved = fetch_data(SETTINGS, "boxes")
    assert [box["settings"]["conf_thresh"] for box in saved] == [0.0, 0.0]

    # a threshold set from now on is kept
    box = memory_storage.find_item_by_name("Home Score")
    box.settings["conf_thresh"] = 0.6
    memory_storage.saveBoxesToStorage()
    memory_storage.clear()
    caplog.clear()
    assert memory_storage.loadBoxesFromStorage() is True
    assert conf_thresholds(memory_storage) == {"Home Score": 0.6, "Time": 0.0}
    assert "Migrated" not in caplog.text


@pytest.mark.parametrize("schema_version", [3, 4])
def test_boxes_with_the_schema_version_are_not_migrated(memory_storage, schema_version):
    store_data(
        SETTINGS, "boxes", [old_box("Shot Clock", 0.5, format_regex=OLD_SHOT_CLOCK)]
    )
    store_data(SETTINGS, storage.BOXES_SCHEMA_KEY, schema_version)
    assert memory_storage.loadBoxesFromStorage() is True
    assert conf_thresholds(memory_storage) == {"Shot Clock": 0.5}
    # a format typed since the upgrade is the user's own
    assert formats(memory_storage) == {"Shot Clock": OLD_SHOT_CLOCK}


def test_saving_boxes_marks_the_schema_version(data_dir, memory_storage):
    memory_storage.add_item(make_box("Home Score", (1, 2, 3, 4), conf_thresh=0.4))
    memory_storage.saveBoxesToStorage()
    settings = read_settings_file(data_dir)
    assert settings[storage.BOXES_SCHEMA_KEY] == 4
    assert settings["boxes"][0]["settings"]["conf_thresh"] == 0.4


def test_exported_file_has_the_schema_version(tmp_path, memory_storage):
    memory_storage.add_item(make_box("Home Score", (1, 2, 3, 4), conf_thresh=0.7))
    export = tmp_path / "config.json"
    memory_storage.saveBoxesToFile(str(export))
    data = json.loads(export.read_text(encoding="utf-8"))
    assert data[storage.BOXES_SCHEMA_KEY] == 4
    assert [box["name"] for box in data["boxes"]] == ["Home Score"]

    memory_storage.clear()
    assert memory_storage.loadBoxesFromFile(str(export)) is True
    assert conf_thresholds(memory_storage) == {"Home Score": 0.7}


def test_configuration_exported_by_0_1_x_is_migrated(tmp_path, memory_storage):
    # 0.1.x exported a plain list of boxes
    export = tmp_path / "old config.json"
    export.write_text(json.dumps([old_box("Away Score", 0.5)]), encoding="utf-8")
    assert memory_storage.loadBoxesFromFile(str(export)) is True
    assert conf_thresholds(memory_storage) == {"Away Score": 0.0}


def test_two_digit_clock_formats_are_migrated(data_dir, memory_storage, caplog):
    # Up to 0.3.0 the Shotclock 0-39 and Time 0-59 presets took exactly two
    # digits, so a shot clock showing 9 (not 09) failed the filter and the
    # outputs froze at 10. Boxes that stored those presets get the new ones.
    assert format_prefixes[5] == "^[0-3]?\\d$"
    assert format_prefixes[4] == "^[0-5]?\\d$"
    store_data(
        SETTINGS,
        "boxes",
        [
            old_box("Shot Clock", 0.5, format_regex=OLD_SHOT_CLOCK),
            old_box("Seconds", 0.4, format_regex=OLD_TIME_0_59, is_custom=True),
            old_box("Home Score", 0.3, format_regex=format_prefixes[6]),
            old_box("Countdown", 0.2, format_regex="^[0-3]\\d\\d$", is_custom=True),
            old_box("Away Score", 0.1),
        ],
    )
    store_data(SETTINGS, storage.BOXES_SCHEMA_KEY, 2)
    assert memory_storage.loadBoxesFromStorage() is True
    assert formats(memory_storage) == {
        "Shot Clock": format_prefixes[5],
        "Seconds": format_prefixes[4],
        # other formats, and boxes without one (their preset's), are untouched
        "Home Score": format_prefixes[6],
        "Countdown": "^[0-3]\\d\\d$",
        "Away Score": format_prefixes[6],
    }
    # schema 2 boxes keep their confidence threshold (that migration is 0.1.x's)
    assert conf_thresholds(memory_storage) == {
        "Shot Clock": 0.5,
        "Seconds": 0.4,
        "Home Score": 0.3,
        "Countdown": 0.2,
        "Away Score": 0.1,
    }
    assert "Migrated the format of 2 box(es)" in caplog.text
    assert "confidence threshold" not in caplog.text
    # saved back once, with the new schema version
    assert (
        fetch_data(SETTINGS, storage.BOXES_SCHEMA_KEY) == storage.BOXES_SCHEMA_VERSION
    )
    saved = {box["name"]: box["settings"] for box in fetch_data(SETTINGS, "boxes")}
    assert saved["Shot Clock"]["format_regex"] == format_prefixes[5]
    assert saved["Seconds"]["format_regex"] == format_prefixes[4]

    caplog.clear()
    memory_storage.clear()
    assert memory_storage.loadBoxesFromStorage() is True
    assert formats(memory_storage)["Shot Clock"] == format_prefixes[5]
    assert "Migrated" not in caplog.text


OLD_TIME_FORMATS = {
    # the Time presets with minutes up to 0.4.2, which took minutes 0-59
    0: "^(?:(?:[0-5]?\\d:[0-5]\\d)|(?:[0-5]?\\d\\.\\d))$",
    1: "^(?:(?:[0-5]?\\d:[0-5]\\d)|(?:[0-5]?\\d[.:]\\d))$",
    2: "^[0-5]?\\d:[0-5]\\d$",
}


def test_time_formats_of_minutes_0_59_are_migrated(data_dir, memory_storage, caplog):
    # Up to 0.4.2 the Time mm:ss presets took minutes 0-59, so a soccer clock
    # was rejected from 60:00 on and the outputs stayed at 59:59 (discussion
    # #163). Boxes that stored those presets get the new ones.
    assert storage.BOXES_SCHEMA_VERSION == 4
    store_data(
        SETTINGS,
        "boxes",
        [
            old_box("Time", 0.5, format_regex=OLD_TIME_FORMATS[0]),
            old_box("Clock", 0.4, format_regex=OLD_TIME_FORMATS[1], is_custom=True),
            old_box("Half", 0.3, format_regex=OLD_TIME_FORMATS[2], is_custom=True),
            # 12-minute quarters, the docs' example of a custom format
            old_box("Q", 0.2, format_regex="^(1[0-2]|[1-9]):[0-5]\\d$", is_custom=True),
        ],
    )
    store_data(SETTINGS, storage.BOXES_SCHEMA_KEY, 3)
    assert memory_storage.loadBoxesFromStorage() is True
    assert formats(memory_storage) == {
        "Time": format_prefixes[0],
        "Clock": format_prefixes[1],
        "Half": format_prefixes[2],
        "Q": "^(1[0-2]|[1-9]):[0-5]\\d$",
    }
    assert conf_thresholds(memory_storage)["Time"] == 0.5
    assert "Migrated the format of 3 box(es)" in caplog.text
    assert "minutes past 59" in caplog.text
    assert (
        fetch_data(SETTINGS, storage.BOXES_SCHEMA_KEY) == storage.BOXES_SCHEMA_VERSION
    )

    caplog.clear()
    memory_storage.clear()
    assert memory_storage.loadBoxesFromStorage() is True
    assert formats(memory_storage)["Time"] == format_prefixes[0]
    assert "Migrated" not in caplog.text


@pytest.mark.parametrize("schema_version", [None, 2, 3, 4])
def test_exported_time_formats_of_minutes_0_59_are_migrated(
    tmp_path, memory_storage, schema_version
):
    boxes = [old_box("Time", 0.5, format_regex=OLD_TIME_FORMATS[2])]
    export = tmp_path / "config.json"
    if schema_version is None:
        content = boxes  # 0.1.x exported a plain list
    else:
        content = {storage.BOXES_SCHEMA_KEY: schema_version, "boxes": boxes}
    export.write_text(json.dumps(content), encoding="utf-8")
    assert memory_storage.loadBoxesFromFile(str(export)) is True
    # a schema 4 file was exported after the upgrade: its format is the user's
    expected = OLD_TIME_FORMATS[2] if schema_version == 4 else format_prefixes[2]
    assert formats(memory_storage) == {"Time": expected}


def test_boxes_from_0_1_x_get_both_migrations(memory_storage):
    store_data(
        SETTINGS, "boxes", [old_box("Shot Clock", 0.5, format_regex=OLD_SHOT_CLOCK)]
    )
    assert memory_storage.loadBoxesFromStorage() is True
    assert conf_thresholds(memory_storage) == {"Shot Clock": 0.0}
    assert formats(memory_storage) == {"Shot Clock": format_prefixes[5]}


@pytest.mark.parametrize(
    ("schema_version", "conf_thresh"), [(None, 0.0), (2, 0.5), (3, 0.5)]
)
def test_exported_two_digit_clock_formats_are_migrated(
    tmp_path, memory_storage, schema_version, conf_thresh
):
    boxes = [old_box("Shot Clock", 0.5, format_regex=OLD_SHOT_CLOCK)]
    export = tmp_path / "config.json"
    if schema_version is None:
        content = boxes  # 0.1.x exported a plain list
    else:
        content = {storage.BOXES_SCHEMA_KEY: schema_version, "boxes": boxes}
    export.write_text(json.dumps(content), encoding="utf-8")
    assert memory_storage.loadBoxesFromFile(str(export)) is True
    assert conf_thresholds(memory_storage) == {"Shot Clock": conf_thresh}
    # a schema 3 file was exported after the upgrade: its format is the user's
    expected = OLD_SHOT_CLOCK if schema_version == 3 else format_prefixes[5]
    assert formats(memory_storage) == {"Shot Clock": expected}


def test_malformed_formats_are_left_alone():
    boxes = [
        {"name": "A", "settings": {"format_regex": ["^[0-3]\\d$"]}},
        {"name": "B", "settings": None},
        "not a box",
    ]
    migrated = storage.migrate_boxes(boxes, "a test", 2)
    assert migrated == boxes


@pytest.mark.parametrize(
    "content", ["{not json", '{"no": "boxes"}', '"text"', '["box"]', "[1]"]
)
def test_invalid_configuration_file_keeps_the_boxes(tmp_path, memory_storage, content):
    memory_storage.add_item(make_box("Home Score", (1, 2, 3, 4)))
    bad = tmp_path / "bad.json"
    bad.write_text(content, encoding="utf-8")
    assert memory_storage.loadBoxesFromFile(str(bad)) is False
    assert memory_storage.loadBoxesFromFile(str(tmp_path / "missing.json")) is False
    assert [box.name for box in memory_storage.get_data()] == ["Home Score"]


# --- the stored OCR model (ocr_models): no migration, its values keep meaning ----------


def test_a_new_setup_gets_ppocr_automatic(data_dir):
    import ocr_models

    assert not ocr_models.is_stored()
    assert ocr_models.stored_model() == ocr_models.PPOCR_AUTO == "ppocr:auto"


@pytest.mark.parametrize("stored", [0, 1, 2, 3])
def test_the_tesseract_model_indexes_of_0_1_and_0_2_keep_their_meaning(
    data_dir, stored
):
    # 0.1 and 0.2 stored the index of the model list, which had the Tesseract
    # models in this order; they are stored as they were, never rewritten
    import ocr_models
    from tesseract import TextDetector

    names = {
        TextDetector.OcrModelIndex.DAKTRONICS: "Tesseract: Daktronics",
        TextDetector.OcrModelIndex.SCOREBOARD_GENERAL: "Tesseract: General Scoreboard",
        TextDetector.OcrModelIndex.GENERAL_ENGLISH: "Tesseract: General Fonts (English)",
        TextDetector.OcrModelIndex.SCOREBOARD_GENERAL_LARGE: (
            "Tesseract: General Scoreboard Large"
        ),
    }
    storage.store_data("scoresight.json", "ocr_model", stored)
    assert ocr_models.stored_model() == stored
    assert ocr_models.is_builtin_tesseract(stored)
    assert ocr_models.choice_name(stored) == names[stored]
    # a stored Tesseract model is used whatever PP-OCR's availability
    assert ocr_models.effective_model(stored) == stored


def test_a_stored_traineddata_path_stays_external(data_dir, tmp_path):
    import ocr_models

    path = str(tmp_path / "my.traineddata")
    storage.store_data("scoresight.json", "ocr_model", path)
    assert ocr_models.stored_model() == path
    assert ocr_models.is_external(path)
    assert not ocr_models.is_external("ppocr:small")
    assert not ocr_models.is_ppocr(path)
    assert ocr_models.choice_name(path) is None


def test_a_stored_ppocr_model_that_cant_be_used_reads_with_tesseract(
    data_dir, monkeypatch
):
    import ocr_models
    import ppocr_engine

    storage.store_data("scoresight.json", "ocr_model", "ppocr:small")
    monkeypatch.setattr(ppocr_engine, "unavailable_reason", lambda model: "missing")
    assert ocr_models.effective_model("ppocr:small") == ocr_models.FALLBACK_MODEL == 1
    # the choice stays stored
    assert ocr_models.stored_model() == "ppocr:small"
    monkeypatch.setattr(ppocr_engine, "unavailable_reason", lambda model: None)
    assert ocr_models.effective_model("ppocr:small") == "ppocr:small"


def test_true_is_not_a_tesseract_index():
    import ocr_models

    assert not ocr_models.is_builtin_tesseract(True)
    assert ocr_models.choice_name(True) is None
