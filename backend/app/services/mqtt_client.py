import asyncio
import logging
from datetime import datetime
import paho.mqtt.client as mqtt

from ..config import settings
from .mqtt_handlers import handle_message

logger = logging.getLogger(__name__)

def _guard_topics() -> list[str]:
    """Guard worker -> backend topics. Built from settings.marina_id, which is explicit and
    never derived from the cabinet id. `cmd` is absent on purpose: the backend publishes it
    and must not consume its own commands."""
    try:
        from ..guard.service import subscription_patterns
        return subscription_patterns()
    except Exception:          # guard package unavailable -> MQTT still works
        return []


# THREE topic families are subscribed. Exactly ONE is published by real hardware.
#
# Corrected 2026-10-01 — the comments below used to label the wrong family "(real hardware)",
# which is how `WTR-1` reached a production allowlist and how a whole family of handlers came
# to be maintained against nothing. A full MQTT capture from MAR_KRK_ORM_01 (firmware 3.1.0,
# 2026-09-29) contains ONLY `opta/...` topics.
#
#   opta/*            REAL. Verified by capture. Everything new targets this.
#   marina/cabinet/*  ASPIRATIONAL. Nothing publishes it, nothing bridges the prefixes, and
#                     every MARINA_* handler fires only from tests. Not to be extended.
#   pedestal/*        LEGACY. The deleted simulator and the manual test tool spoke this.
#                     Kept because the test tool still exists; no firmware has ever used it.
#
# Subscribing to all three is cheap and harmless. BELIEVING all three is what cost us.
TOPICS = [
    # Legacy pedestal/... schema — test tool only; the simulator that spoke it was deleted
    # 2026-03-15 (be0df4f). No firmware publishes this.
    "pedestal/+/socket/+/status",
    "pedestal/+/socket/+/power",
    "pedestal/+/water/flow",
    "pedestal/+/heartbeat",
    "pedestal/+/sensors/temperature",
    "pedestal/+/sensors/moisture",
    "pedestal/+/diagnostics/response",
    "pedestal/+/register",
    # Marina cabinet schema — ASPIRATIONAL, NOT real hardware. This comment said
    # "(real hardware)" and said the opposite of the truth. Do not extend; do not let new
    # code assume these topics exist.
    "marina/cabinet/+/sockets/+/state",
    "marina/cabinet/+/water/+/state",
    "marina/cabinet/+/door/state",
    "marina/cabinet/+/status",
    "marina/cabinet/+/events",
    "marina/cabinet/+/acks",
    # Opta firmware schema — THE REAL ONE. cabinetId is in the payload, not the topic path.
    "opta/status",
    "opta/sockets/+/status",
    "opta/sockets/+/power",
    "opta/water/+/status",
    "opta/door/status",
    "opta/events",
    "opta/acks",
    "opta/diagnostic",
    # v3.8 — per-socket breaker status; socket_id is taken from the topic path.
    "opta/breakers/+/status",
    # v3.11 — cabinet hardware configuration (one shot per cabinet) + live
    # per-socket meter telemetry every 5 s.
    "opta/config/hardware",
    "opta/meters/+/telemetry",
] + _guard_topics()


class MQTTService:
    def __init__(self):
        self._loop: asyncio.AbstractEventLoop | None = None
        self._client: mqtt.Client | None = None
        self._connected = False
        # v3.16 — broker status instrumentation (for the status snapshot file).
        self._last_connect_at: datetime | None = None
        self._last_disconnect_at: datetime | None = None
        self._last_disconnect_reason: str | None = None
        self._connect_count = 0

    def status(self) -> dict:
        """Current broker connection status (for /api/system/mqtt-status + file)."""
        def _iso(dt):
            return (dt.isoformat() + "Z") if dt else None
        return {
            "connected": self._connected,
            "broker_host": settings.mqtt_broker_host,
            "broker_port": settings.mqtt_broker_port,
            "keepalive": 60,
            "last_connect_at": _iso(self._last_connect_at),
            "last_disconnect_at": _iso(self._last_disconnect_at),
            "last_disconnect_reason": self._last_disconnect_reason,
            "connect_count": self._connect_count,
            "subscribed_topics": list(TOPICS),
        }

    def start(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop
        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._client.on_disconnect = self._on_disconnect

        try:
            # Exponential back-off: retry in 1s, 2s, 4s … up to 30s between attempts
            self._client.reconnect_delay_set(min_delay=1, max_delay=30)
            self._client.connect(settings.mqtt_broker_host, settings.mqtt_broker_port, keepalive=60)
            self._client.loop_start()
            logger.info(f"MQTT client connecting to {settings.mqtt_broker_host}:{settings.mqtt_broker_port}")
        except Exception as e:
            logger.error(f"Failed to connect MQTT client: {e}")
            try:
                from .error_log_service import log_error
                log_error(
                    "hw", "mqtt_client",
                    f"MQTT broker unreachable ({settings.mqtt_broker_host}:{settings.mqtt_broker_port})",
                    details=str(e),
                )
            except Exception:
                pass

    def stop(self):
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()
            logger.info("MQTT client stopped")

    def publish(self, topic: str, payload: str, qos: int = 1):
        if self._client and self._connected:
            self._client.publish(topic, payload, qos=qos)
            logger.debug(f"MQTT publish → {topic}: {payload}")
        else:
            logger.warning(f"MQTT not connected, cannot publish to {topic}")
            try:
                from .error_log_service import log_warning
                log_warning("hw", "mqtt_client", f"Publish failed — not connected. Topic: {topic}")
            except Exception:
                pass

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            self._connected = True
            self._last_connect_at = datetime.utcnow()
            self._connect_count += 1
            logger.info("MQTT connected")
            for topic in TOPICS:
                client.subscribe(topic, qos=1)
                logger.info(f"Subscribed to {topic}")
        else:
            logger.error(f"MQTT connection failed with reason code {reason_code}")
            try:
                from .error_log_service import log_error
                log_error("hw", "mqtt_client", f"MQTT connection failed (reason code {reason_code})")
            except Exception:
                pass

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        self._connected = False
        self._last_disconnect_at = datetime.utcnow()
        self._last_disconnect_reason = str(reason_code)
        logger.warning(f"MQTT disconnected (reason: {reason_code})")
        if reason_code != 0:  # 0 = clean disconnect
            try:
                from .error_log_service import log_warning
                log_warning("hw", "mqtt_client", f"MQTT broker disconnected unexpectedly (code {reason_code})")
            except Exception:
                pass

    def _on_message(self, client, userdata, msg):
        topic = msg.topic
        try:
            payload = msg.payload.decode("utf-8")
        except Exception:
            payload = str(msg.payload)

        # v3.40 — forward the RETAIN flag. The broker replays the last retained
        # message per topic to every new subscriber, so on each backend restart a
        # long-dead cabinet's final status arrives looking exactly like a live
        # one. Without this flag the handlers cannot tell the two apart and stamp
        # the cabinet `online` with a fresh heartbeat. See handle_message().
        retained = bool(getattr(msg, "retain", False))

        logger.debug(f"MQTT received ← {topic}{' [retained]' if retained else ''}: {payload}")

        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(
                handle_message(topic, payload, retained=retained), self._loop,
            )

    @property
    def is_connected(self) -> bool:
        return self._connected


mqtt_service = MQTTService()
