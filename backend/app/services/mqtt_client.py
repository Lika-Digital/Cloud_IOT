import asyncio
import logging
import paho.mqtt.client as mqtt

from ..config import settings
from .mqtt_handlers import handle_message

logger = logging.getLogger(__name__)

TOPICS = [
    "pedestal/+/socket/+/status",
    "pedestal/+/socket/+/power",
    "pedestal/+/water/flow",
    "pedestal/+/heartbeat",
    "pedestal/+/sensors/temperature",
    "pedestal/+/sensors/moisture",
    "pedestal/+/diagnostics/response",
]


class MQTTService:
    def __init__(self):
        self._loop: asyncio.AbstractEventLoop | None = None
        self._client: mqtt.Client | None = None
        self._connected = False

    def start(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop
        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._client.on_disconnect = self._on_disconnect

        try:
            self._client.connect(settings.mqtt_broker_host, settings.mqtt_broker_port, keepalive=60)
            self._client.loop_start()
            logger.info(f"MQTT client connecting to {settings.mqtt_broker_host}:{settings.mqtt_broker_port}")
        except Exception as e:
            logger.error(f"Failed to connect MQTT client: {e}")

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

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            self._connected = True
            logger.info("MQTT connected")
            for topic in TOPICS:
                client.subscribe(topic, qos=1)
                logger.info(f"Subscribed to {topic}")
        else:
            logger.error(f"MQTT connection failed with reason code {reason_code}")

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        self._connected = False
        logger.warning(f"MQTT disconnected (reason: {reason_code})")

    def _on_message(self, client, userdata, msg):
        topic = msg.topic
        try:
            payload = msg.payload.decode("utf-8")
        except Exception:
            payload = str(msg.payload)

        logger.debug(f"MQTT received ← {topic}: {payload}")

        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(handle_message(topic, payload), self._loop)

    @property
    def is_connected(self) -> bool:
        return self._connected


mqtt_service = MQTTService()
