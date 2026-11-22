"""vMix output: sets text fields of a vMix title through the vMix Web API
(served by vMix's Web Controller, port 8088 by default).

update_vmix() is called on the GUI thread. It only queues the changed values;
a background OutputWorker sends them (latest value per field wins), so a slow or
unreachable vMix never blocks the UI.
"""

from collections.abc import Container
from urllib.parse import quote, urlencode

import requests

from output_worker import HTTP_TIMEOUT, OutputWorker, check_http_response
from sc_logging import logger
from storage import fetch_data, subscribe_to_data, unsubscribe_from_data
from text_detection_target import TextDetectionTargetWithResult

# vMix's HTTP Web API (Settings > Web Controller). 8099 is vMix's raw TCP API,
# which doesn't speak HTTP.
DEFAULT_VMIX_PORT = "8088"
VMIX_TCP_API_PORT = "8099"


class VMixTCPPortError(requests.ConnectionError):
    """vMix answered with its TCP API greeting ("VERSION OK ...") instead of HTTP."""


class VMixAPI:
    def __init__(self, host, port, input_number, field_mapping):
        self.host = host
        self.port = port
        self.input_number = input_number
        # read by the worker thread; replaced as a whole so it's always consistent
        self._target = (host, port, input_number)
        self.field_mapping = field_mapping
        self.running = False
        self.update_same = fetch_data("scoresight.json", "vmix_send_same", False)
        subscribe_to_data("scoresight.json", "vmix_send_same", self.set_update_same)
        self._session = requests.Session()  # used only by the worker thread
        self._worker = OutputWorker(
            "vMix",
            self._send_text,
            retry_on=(requests.ConnectionError, requests.Timeout),
        )

    def set_update_same(self, update_same):
        self.update_same = update_same

    def set_field_mapping(self, field_mapping):
        self.field_mapping = field_mapping

    def set_connection(self, host, port, input_number):
        """Send to another host/port/input from now on. The field mapping and the
        running state are kept; values not sent yet go to the new target."""
        if (host, port, input_number) == self._target:
            return
        self.host, self.port, self.input_number = host, port, input_number
        self._target = (host, port, input_number)
        # the status (and the errors logged) are about the new target
        self._worker.reset_status()

    def start(self):
        self.running = True

    def stop(self):
        self.running = False
        self._worker.clear()
        self._worker.reset_status()

    def status(self):
        """The sending's WorkerStatus (see output_worker)."""
        return self._worker.status()

    def close(self):
        """Stop sending and unsubscribe from settings changes."""
        self.stop()
        unsubscribe_from_data("scoresight.json", "vmix_send_same", self.set_update_same)
        self._worker.stop()

    def update_vmix(
        self,
        detection: list[TextDetectionTargetWithResult],
        resend_unchanged: Container[str] = (),
    ):
        """Queue the new values of the mapped fields. Never blocks.
        The boxes named in resend_unchanged also send an unchanged value (as
        "Also resend unchanged values" does for every box), e.g. after the outputs were paused."""
        if not self.running:
            return

        if not self.field_mapping:
            logger.debug("Field mapping is not set")
            return

        for target in detection:
            if not (
                target.result_state == TextDetectionTargetWithResult.ResultState.Success
                or (
                    target.result_state
                    == TextDetectionTargetWithResult.ResultState.SameNoChange
                    and (self.update_same or target.name in resend_unchanged)
                )
            ):
                continue
            field = self.field_mapping.get(target.name)
            if not field:
                continue
            value = "" if target.result is None else str(target.result)
            self._worker.submit(field, value)

    def url_for(self, field: str, value: str) -> str:
        host, port, input_number = self._target
        query = {
            "Function": "SetText",
            "Input": input_number,
            "SelectedName": field,
            "Value": value,
        }
        # spaces as %20, not "+": vMix may not decode "+" as a space
        return f"http://{host}:{port}/api/?{urlencode(query, quote_via=quote)}"

    def _send_text(self, field: str, value: str) -> None:
        # runs on the worker thread
        url = self.url_for(field, value)
        try:
            response = self._session.get(url, timeout=HTTP_TIMEOUT)
        except requests.ConnectionError as e:
            if "VERSION OK" in str(e):
                host, port, _ = self._target
                raise VMixTCPPortError(
                    f"{host}:{port} answered like the vMix TCP API ('VERSION OK'). "
                    "ScoreSight uses the vMix Web API: set the port to the Web "
                    f"Controller port (vMix Settings > Web Controller, "
                    f"{DEFAULT_VMIX_PORT} by default), not {VMIX_TCP_API_PORT}."
                ) from e
            raise
        check_http_response(response, f"SetText {field!r}")
        logger.debug("vMix: set %s to %r", field, value)
