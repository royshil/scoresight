import functools
import json
import logging
import threading
import weakref
from os import path

import obsws_python as obs
import websocket
from obsws_python.error import OBSSDKRequestError, OBSSDKTimeoutError

from output_worker import ErrorInfo, OutputWorker, SendSkipped
from resource_path import resource_path
from sc_logging import logger

# obsws-python logs the connection parameters, including the OBS password, at
# INFO, and every failed request with a traceback at ERROR (so once per cycle
# for a missing text source). ScoreSight logs OBS problems itself (throttled).
logging.getLogger("obsws_python").setLevel(logging.CRITICAL)

# seconds to wait for OBS to connect or to answer a request
OBS_TIMEOUT = 3

# errors that mean the websocket connection is broken (or out of sync after a
# timeout) and has to be re-established. The close frame of an OBS that is
# shutting down (or restarting its websocket server) reads as an empty
# response, which fails to parse as JSON.
_CONNECTION_ERRORS = (
    OSError,
    websocket.WebSocketException,
    OBSSDKTimeoutError,
    json.JSONDecodeError,
)


class OBSConnectionLost(Exception):
    """The connection to OBS broke and could not be re-established (yet)."""


# A ReqClient is a single websocket with no locking: each request is a send()
# followed by a recv(). The background text updates and the scene functions
# called from the GUI thread take the client's lock so they never interleave.
_client_locks: "weakref.WeakKeyDictionary[object, threading.RLock]" = (
    weakref.WeakKeyDictionary()
)
_client_locks_guard = threading.Lock()
_closed_clients: "weakref.WeakSet[object]" = weakref.WeakSet()


def client_lock(obs_client) -> threading.RLock:
    """The lock that serializes all requests on obs_client."""
    with _client_locks_guard:
        lock = _client_locks.get(obs_client)
        if lock is None:
            lock = _client_locks[obs_client] = threading.RLock()
        return lock


def _locked(func):
    """Run func(obs_client, ...) holding obs_client's lock."""

    @functools.wraps(func)
    def wrapper(obs_client, *args, **kwargs):
        if obs_client is None:
            return func(obs_client, *args, **kwargs)
        with client_lock(obs_client):
            return func(obs_client, *args, **kwargs)

    return wrapper


# why the last open_obs_websocket() call of a thread failed
_connect_errors = threading.local()


def open_obs_websocket(server_info):
    """Connect to OBS. Returns the client, or None if it failed: then
    last_connect_error() (on the same thread) tells why."""
    _connect_errors.last = None
    try:
        cl = obs.ReqClient(
            host=server_info["ip"],
            port=server_info["port"],
            password=server_info["password"],
            timeout=OBS_TIMEOUT,
        )
        resp = cl.get_version()
        logger.info(f"OBS Version: {resp.obs_version}")
        return cl
    except Exception as e:
        _connect_errors.last = ErrorInfo.of(e)
        logger.warning(f"Cannot connect to OBS: {type(e).__name__}: {e}")
        return None


def last_connect_error() -> ErrorInfo | None:
    """Why the last open_obs_websocket() call on this thread failed."""
    return getattr(_connect_errors, "last", None)


def obs_client_address(obs_client) -> str | None:
    """The "host:port" of an OBS client's connection."""
    base = getattr(obs_client, "base_client", None)
    host, port = getattr(base, "host", None), getattr(base, "port", None)
    if host is None:
        return None
    return f"{host}:{port}" if port is not None else str(host)


def close_obs_websocket(obs_client) -> None:
    """Disconnect obs_client and drop its pending text updates (call it when the
    client is replaced or the app closes)."""
    if obs_client is None:
        return
    _closed_clients.add(obs_client)
    # its text sources are no longer this output's concern
    client_id = id(obs_client)
    _text_worker.forget_keys(lambda key: key[0] == client_id)
    with client_lock(obs_client):
        try:
            obs_client.disconnect()
        except Exception as e:
            logger.debug(f"OBS: error while disconnecting: {e}")


def _reconnect(obs_client) -> None:
    """Replace obs_client's broken websocket with a new, authenticated one.
    Raises OBSConnectionLost if OBS can't be reached. Call with the lock held."""
    base = getattr(obs_client, "base_client", None)
    if base is None:
        raise OBSConnectionLost("connection to OBS lost")
    try:
        base.ws.shutdown()  # close the socket without a close handshake
    except Exception:
        pass
    try:
        fresh = obs.ReqClient(
            host=base.host,
            port=base.port,
            password=base.password,
            timeout=base.timeout,
        )
    except Exception as e:
        raise OBSConnectionLost(
            f"connection to OBS at {base.host}:{base.port} lost, reconnecting "
            f"failed: {type(e).__name__}: {e}"
        ) from e
    obs_client.base_client = fresh.base_client
    logger.info(f"OBS: reconnected to {base.host}:{base.port}")


def _set_text(_key, item) -> None:
    # runs on the OBS output worker thread
    obs_client, source_name, text = item
    if obs_client in _closed_clients:
        raise SendSkipped()
    with client_lock(obs_client):
        # close_obs_websocket marks the client closed before it takes the lock:
        # if that happened while this waited for the lock, don't reconnect it
        if obs_client in _closed_clients:
            raise SendSkipped()
        try:
            obs_client.set_input_settings(source_name, {"text": text}, True)
        except _CONNECTION_ERRORS:
            _reconnect(obs_client)
            obs_client.set_input_settings(source_name, {"text": text}, True)


_text_worker = OutputWorker(
    "OBS",
    _set_text,
    retry_on=(OBSConnectionLost,) + _CONNECTION_ERRORS,
    max_backoff=10.0,
)


def obs_output_status():
    """The text updates' WorkerStatus (see output_worker), for every client."""
    return _text_worker.status()


# obs-websocket's request status when an output (the replay buffer) is off
_OUTPUT_NOT_RUNNING = 501


class ReplayBufferOff(Exception):
    """OBS's replay buffer isn't running, so it has nothing to save."""


@_locked
def save_replay_buffer(obs_client: obs.ReqClient) -> None:
    """Ask OBS to save its replay buffer as a clip (blocking: call it off the
    GUI thread). Reconnects once if the connection broke. Raises
    ReplayBufferOff if the replay buffer isn't running, and OBS's or the
    connection's error otherwise."""
    if obs_client in _closed_clients:
        raise SendSkipped()
    try:
        try:
            obs_client.save_replay_buffer()
        except _CONNECTION_ERRORS:
            _reconnect(obs_client)
            obs_client.save_replay_buffer()
    except OBSSDKRequestError as e:
        if e.code == _OUTPUT_NOT_RUNNING:
            raise ReplayBufferOff() from e
        raise


@_locked
def get_all_sources(obs_client: obs.ReqClient):
    # Get all the sources from OBS
    try:
        # get all scenes
        resp = obs_client.get_scene_list()
        scenes = resp.scenes
        # get all sources from all scenes
        sources = []
        for scene in scenes:
            resp = obs_client.get_scene_item_list(scene["sceneName"])
            # add the sources with their scene name
            for source in resp.scene_items:
                source["sceneName"] = scene["sceneName"]
                sources.append(source)
        return sources
    except Exception:
        logger.exception("Error: unable to get all sources")
        return None


@_locked
def get_source_by_name(obs_client: obs.ReqClient, source_name):
    # Get a source from OBS by name
    try:
        # get all scenes
        resp = obs_client.get_scene_list()
        scenes = resp.scenes
        # get all sources from all scenes
        sources = []
        for scene in scenes:
            resp = obs_client.get_scene_item_list(scene["sceneName"])
            # add the sources with their scene name
            for source in resp.scene_items:
                source["sceneName"] = scene["sceneName"]
                sources.append(source)
        # find the source by name
        for source in sources:
            if source["sourceName"] == source_name:
                return source
        return None
    except Exception:
        logger.exception("Error: unable to get source by name")
        return None


@_locked
def get_source_screenshot(obs_client: obs.ReqClient, source_name, width, height):
    # Get a screenshot of a source from OBS
    try:
        resp = obs_client.get_source_screenshot(
            source_name, img_format="png", width=width, height=height, quality=100
        )
        return resp.image_data
    except Exception:
        logger.exception("Error: unable to get source screenshot")
        return None


def update_text_source(obs_client: obs.ReqClient, source_name, text) -> None:
    """Set the text of the OBS text source source_name, in the background.

    Never blocks: the update is queued for the OBS output thread, which keeps
    only the latest text per source and reconnects if the connection broke.
    Boxes without an OBS source name are skipped."""
    if obs_client is None or not source_name:
        return
    text = "" if text is None else str(text)
    _text_worker.submit((id(obs_client), source_name), (obs_client, source_name, text))


# What create_obs_scene_from_export did with the scene
SCENE_CREATED = "created"  # there was no scene with that name
SCENE_RECREATED = "recreated"  # the existing scene was emptied and made again
SCENE_KEPT = "kept"  # the scene exists and Recreate is off: left as it is
SCENE_FAILED = "failed"  # OBS couldn't be asked or refused (see the log)


@_locked
def obs_scene_exists(obs_client: obs.ReqClient, scene_name) -> bool | None:
    """Whether OBS has a scene with this name; None if OBS can't be asked."""
    try:
        resp = obs_client.get_scene_list()
    except Exception:
        logger.exception("Error: unable to get scene list")
        return None
    return any(scene["sceneName"] == scene_name for scene in resp.scenes)


@_locked
def clear_or_create_new_scene(obs_client: obs.ReqClient, scene_name) -> bool:
    # Create a new scene in OBS or clear an existing one
    try:
        # check if the scene exists
        resp = obs_client.get_scene_list()
    except Exception:
        logger.exception("Error: unable to get scene list")
        return False
    scenes = resp.scenes
    scene_exists = False
    for scene in scenes:
        if scene["sceneName"] == scene_name:
            scene_exists = True
            break
    # if the scene doesnt exist, create it
    if not scene_exists:
        # create a new scene
        try:
            obs_client.create_scene(scene_name)
            return True
        except Exception as e:
            logger.exception(f"Cannot create scene. Error: {e}")
            return False

    try:
        # if the scene is currently selected in OBS, switch to another scene
        resp = obs_client.get_current_program_scene()
        if resp.current_program_scene_name == scene_name:
            # get the first scene that is not the current scene
            for scene in scenes:
                if scene["sceneName"] != scene_name:
                    obs_client.set_current_program_scene(scene["sceneName"])
                    break
    except Exception:
        logger.exception("Cannot change OBS program scene")

    try:
        resp = obs_client.get_current_preview_scene()
        if resp.current_preview_scene_name == scene_name:
            # get the first scene that is not the current scene
            for scene in scenes:
                if scene["sceneName"] != scene_name:
                    obs_client.set_current_preview_scene(scene["sceneName"])
                    break
    except Exception:
        logger.exception("Cannot change OBS preview scene")

    _empty_scene(obs_client, scene_name)
    return True


# the scene of the bundled scene collection whose items Create OBS Scene makes
_TEMPLATE_SCENE_UUID = "6656641a-06b4-41e5-8a06-0de8a25e38be"


def _load_scene_template() -> tuple[list[dict], list[dict]]:
    """The items of the bundled scoreboard scene and the collection's sources."""
    obs_data_path = resource_path("obs_data", "Scoresight_OBS_scene_collection.json")
    logger.debug(f"loading scene from '{obs_data_path}'")
    with open(obs_data_path, "r") as f:
        collection = json.load(f)
    scene_source = [
        source
        for source in collection["sources"]
        if source["uuid"] == _TEMPLATE_SCENE_UUID
    ][0]
    return scene_source["settings"]["items"], collection["sources"]


def scoresight_input_kinds() -> dict[str, set[str]]:
    """{input name: its input kinds (versioned and not)} of the inputs Create
    OBS Scene makes. An input in OBS with one of these names and kinds is
    taken to be one ScoreSight made."""
    items, sources = _load_scene_template()
    by_uuid = {source["uuid"]: source for source in sources}
    kinds: dict[str, set[str]] = {}
    for item in items:
        source = by_uuid.get(item["source_uuid"])
        if source is None or source.get("id") == "scene":
            continue  # a group or a nested scene: not an input it creates
        kinds[item["name"]] = {
            kind for kind in (source.get("id"), source.get("versioned_id")) if kind
        }
    return kinds


def _sources_used_outside(obs_client, scene_name) -> set[str] | None:
    """The names of the sources that a scene or group other than scene_name
    uses, or None if OBS can't tell."""
    try:
        used: set[str] = set()
        for scene in obs_client.get_scene_list().scenes:
            if scene["sceneName"] == scene_name:
                continue
            for item in obs_client.get_scene_item_list(scene["sceneName"]).scene_items:
                used.add(item["sourceName"])
        for group in obs_client.get_group_list().groups:
            group_name = group if isinstance(group, str) else group.get("sceneName")
            for item in obs_client.get_group_scene_item_list(group_name).scene_items:
                used.add(item["sourceName"])
        return used
    except Exception:
        logger.exception("OBS: unable to tell which sources other scenes use")
        return None


def _empty_scene(obs_client, scene_name) -> None:
    """Remove the items of scene_name, for Create OBS Scene's Recreate.

    Inputs are global in OBS: RemoveInput deletes an input from every scene.
    So only the scene's items are removed (RemoveSceneItem), and an input
    itself only if ScoreSight made it (its name and kind are those of an input
    Create OBS Scene makes) and no other scene or group uses it. A user's
    source, or one shared with another scene, is never deleted.
    """
    try:
        items = obs_client.get_scene_item_list(scene_name).scene_items
    except Exception:
        logger.exception("Error: unable to list the items of scene '%s'", scene_name)
        return
    ours = scoresight_input_kinds()
    used_elsewhere = _sources_used_outside(obs_client, scene_name)
    removed_inputs: set[str] = set()
    for item in items:
        name = item.get("sourceName")
        if name in removed_inputs:
            continue  # another item of an input that was removed already
        removable = (
            used_elsewhere is not None
            and name in ours
            and name not in used_elsewhere
            and item.get("inputKind") in ours[name]
        )
        try:
            if removable:
                obs_client.remove_input(name)
                removed_inputs.add(name)
            else:
                obs_client.remove_scene_item(scene_name, item["sceneItemId"])
        except Exception:
            # an item that can't be removed doesn't stop the others
            logger.exception("Error: unable to remove '%s' from '%s'", name, scene_name)


def _existing_inputs(obs_client) -> dict[str, str | None]:
    """{name: input kind} of the inputs OBS has ({} if it can't tell)."""
    try:
        inputs = obs_client.get_input_list().inputs
    except Exception:
        logger.exception("OBS: unable to list the inputs")
        return {}
    return {entry["inputName"]: entry.get("inputKind") for entry in inputs}


@_locked
def create_obs_scene_from_export(obs_client, scene_name, recreate: bool = True) -> str:
    """Make the ScoreSight scene (its text sources and images) in OBS. A scene
    with this name that exists already is emptied and made again only with
    recreate; otherwise it is kept as it is. Returns SCENE_CREATED,
    SCENE_RECREATED, SCENE_KEPT or SCENE_FAILED."""
    exists = obs_scene_exists(obs_client, scene_name)
    if exists is None:
        return SCENE_FAILED
    if exists and not recreate:
        logger.info(
            "OBS scene '%s' exists and Recreate is off: it is kept as it is",
            scene_name,
        )
        return SCENE_KEPT
    logger.info("creating OBS scene")
    # create a new scene in OBS
    if not clear_or_create_new_scene(obs_client, scene_name):
        return SCENE_FAILED

    template_items, sources_settings = _load_scene_template()
    # inputs that are still there (shared with another scene, or a user's):
    # they get a scene item in this scene instead of a new input
    existing = _existing_inputs(obs_client)

    for source in template_items:
        # if the source is a scene, skip it
        logger.debug(f"creating source {source['name']}")
        # find source settings in sources_settings by the uuid
        source_settings = [
            settings
            for settings in sources_settings
            if settings["uuid"] == source["source_uuid"]
        ]
        if len(source_settings) == 0:
            logger.debug(f"source {source['name']} has no settings, possibly a group")
            continue
        source_settings = source_settings[0]
        # merge settings with source['settings']
        source_settings_to_set = {**source_settings["settings"], **source}
        if "file" in source_settings_to_set:
            # get the base name of the image path
            base_name = path.basename(source_settings_to_set["file"])
            # get the absolute path to the image
            abs_path = resource_path("obs_data", "Scoreboard parts", base_name)
            source_settings_to_set["file"] = abs_path

        kinds = {source_settings.get("id"), source_settings["versioned_id"]}
        reuse = source["name"] in existing
        if reuse and existing[source["name"]] not in kinds:
            logger.warning(
                "OBS already has an input named '%s' of another kind (%s): it "
                "is not added to the scene",
                source["name"],
                existing[source["name"]],
            )
            continue
        try:
            if reuse:
                # keep the existing input with its settings and filters (other
                # scenes may use it): only add it to this scene
                obs_client.create_scene_item(
                    scene_name, source["name"], source_settings_to_set["visible"]
                )
            else:
                # create a new source in OBS
                obs_client.create_input(
                    sceneName=scene_name,
                    inputName=source["name"],
                    inputKind=source_settings["versioned_id"],
                    inputSettings=source_settings_to_set,
                    sceneItemEnabled=source_settings_to_set["visible"],
                )
            # set the SetSceneItemTransform
            if "pos" in source_settings_to_set:
                # get the scene item id with GetSceneItemId
                scene_item_id = obs_client.get_scene_item_id(
                    scene_name, source["name"]
                ).scene_item_id

                transform_to_set = {
                    "alignment": source_settings_to_set["align"],
                    "cropBottom": source_settings_to_set["crop_bottom"],
                    "cropLeft": source_settings_to_set["crop_left"],
                    "cropRight": source_settings_to_set["crop_right"],
                    "cropTop": source_settings_to_set["crop_top"],
                    "positionX": source_settings_to_set["pos"]["x"],
                    "positionY": source_settings_to_set["pos"]["y"],
                    "scaleX": source_settings_to_set["scale"]["x"],
                    "scaleY": source_settings_to_set["scale"]["y"],
                }

                obs_client.set_scene_item_transform(
                    scene_name, scene_item_id, transform_to_set
                )
            # set the filters (an input that was kept has its own)
            if "filters" in source_settings and not reuse:
                for filter in source_settings["filters"]:
                    logger.debug(
                        f"creating filter {filter['name']} for source {source_settings['name']}"
                    )
                    # if the filter has "image_path" in the settings, adjust the path to the obs_data folder
                    if "image_path" in filter["settings"]:
                        # get the base name of the image path
                        base_name = path.basename(filter["settings"]["image_path"])
                        # get the absolute path to the image
                        abs_path = resource_path(
                            "obs_data", "Scoreboard parts", base_name
                        )
                        filter["settings"]["image_path"] = abs_path
                    obs_client.create_source_filter(
                        source["name"],
                        filter["name"],
                        filter["versioned_id"],
                        filter["settings"],
                    )
        except Exception as e:
            logger.exception(f"Unable to create input and filters. Error: {e}")

    logger.info("finished creating sources")
    return SCENE_RECREATED if exists else SCENE_CREATED
