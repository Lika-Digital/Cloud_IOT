"""
Manages async MQTT-based pedestal diagnostics requests.

Flow:
  1. API endpoint calls wait_for_result(pedestal_id) — creates Event, awaits it
  2. MQTT handler calls complete_request(pedestal_id, result) when response arrives
  3. Event is set → API endpoint receives result and returns it to frontend
"""
import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Sensor names expected in a diagnostics response
EXPECTED_SENSORS = ["socket_1", "socket_2", "socket_3", "socket_4",
                    "water", "temperature", "moisture", "camera"]


class DiagnosticsManager:
    def __init__(self):
        self._events: dict[int, asyncio.Event] = {}
        self._results: dict[int, dict] = {}

    async def wait_for_result(self, pedestal_id: int, timeout: float = 12.0) -> Optional[dict]:
        """
        Await a diagnostics response for `pedestal_id`.
        Returns the result dict on success, None on timeout.
        """
        event = asyncio.Event()
        self._events[pedestal_id] = event
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
            return self._results.get(pedestal_id)
        except asyncio.TimeoutError:
            logger.warning(f"Diagnostics timeout for pedestal {pedestal_id}")
            return None
        finally:
            self._events.pop(pedestal_id, None)
            self._results.pop(pedestal_id, None)

    def complete_request(self, pedestal_id: int, result: dict):
        """Called from the MQTT handler when a diagnostics response arrives."""
        self._results[pedestal_id] = result
        event = self._events.get(pedestal_id)
        if event:
            event.set()
            logger.info(f"Diagnostics response received for pedestal {pedestal_id}: {result}")
        else:
            logger.debug(f"Diagnostics result for pedestal {pedestal_id} — no waiter registered")


diagnostics_manager = DiagnosticsManager()
