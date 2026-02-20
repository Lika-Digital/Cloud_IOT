#!/usr/bin/env python3
"""
Pedestal Simulator — simulates an Arduino Opta pedestal over MQTT.
Usage: python pedestal_simulator.py --pedestal-id 1 --broker-host localhost --broker-port 1883
"""
import argparse
import json
import logging
import signal
import sys
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

# Allow running from simulator/ directory or project root
sys.path.insert(0, str(__file__).replace("pedestal_simulator.py", ""))
from generators import PowerGenerator, WaterGenerator, SocketStateManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [SIM] %(message)s")
logger = logging.getLogger(__name__)

POWER_INTERVAL = 2.0   # seconds between power readings
WATER_INTERVAL = 2.0   # seconds between water readings
HEARTBEAT_INTERVAL = 10.0


class PedestalSimulator:
    def __init__(self, pedestal_id: int, broker_host: str, broker_port: int):
        self.pedestal_id = pedestal_id
        self.broker_host = broker_host
        self.broker_port = broker_port
        self._running = False

        # Per-socket state
        self._socket_states = [SocketStateManager(i + 1) for i in range(4)]
        self._power_generators = [PowerGenerator(i + 1) for i in range(4)]
        self._water_generator = WaterGenerator()

        # MQTT client
        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

        # Timing
        self._last_power_time = 0.0
        self._last_water_time = 0.0
        self._last_heartbeat_time = 0.0

    def _topic(self, suffix: str) -> str:
        return f"pedestal/{self.pedestal_id}/{suffix}"

    def _publish(self, topic: str, payload):
        if isinstance(payload, dict):
            payload = json.dumps(payload)
        self._client.publish(topic, payload, qos=1)

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            logger.info(f"Connected to broker {self.broker_host}:{self.broker_port}")
            # Subscribe to control topics
            client.subscribe(self._topic("socket/+/control"))
            client.subscribe(self._topic("water/control"))
        else:
            logger.error(f"Connection failed: {reason_code}")

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        logger.warning(f"Disconnected from broker (reason: {reason_code})")

    def _on_message(self, client, userdata, msg):
        payload = msg.payload.decode("utf-8")
        logger.info(f"Control received ← {msg.topic}: {payload}")
        # In a real pedestal, this would trigger relay action
        # Simulator acknowledges but doesn't need to change state (backend drives session state)

    def run(self):
        self._running = True
        logger.info(f"Simulator starting for pedestal {self.pedestal_id}")

        try:
            self._client.connect(self.broker_host, self.broker_port, keepalive=60)
        except Exception as e:
            logger.error(f"Cannot connect to broker: {e}")
            sys.exit(1)

        self._client.loop_start()
        # Wait for connection
        time.sleep(1.5)

        try:
            while self._running:
                now = time.time()

                # Socket status changes
                for state_mgr in self._socket_states:
                    event = state_mgr.tick()
                    if event:
                        topic = self._topic(f"socket/{state_mgr.socket_id}/status")
                        self._publish(topic, f'"{event}"')
                        logger.info(f"Socket {state_mgr.socket_id}: {event}")

                # Power readings for connected sockets
                if now - self._last_power_time >= POWER_INTERVAL:
                    self._last_power_time = now
                    for i, state_mgr in enumerate(self._socket_states):
                        if state_mgr.connected:
                            reading = self._power_generators[i].next_reading()
                            topic = self._topic(f"socket/{state_mgr.socket_id}/power")
                            self._publish(topic, reading)

                # Water flow readings
                if now - self._last_water_time >= WATER_INTERVAL:
                    self._last_water_time = now
                    reading = self._water_generator.next_reading()
                    topic = self._topic("water/flow")
                    self._publish(topic, reading)

                # Heartbeat
                if now - self._last_heartbeat_time >= HEARTBEAT_INTERVAL:
                    self._last_heartbeat_time = now
                    heartbeat = {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "online": True,
                    }
                    self._publish(self._topic("heartbeat"), heartbeat)

                time.sleep(0.5)

        except KeyboardInterrupt:
            logger.info("Simulator interrupted")
        finally:
            self.stop()

    def stop(self):
        self._running = False
        self._client.loop_stop()
        self._client.disconnect()
        logger.info("Simulator stopped")


def main():
    parser = argparse.ArgumentParser(description="Pedestal MQTT Simulator")
    parser.add_argument("--pedestal-id", type=int, default=1)
    parser.add_argument("--broker-host", type=str, default="localhost")
    parser.add_argument("--broker-port", type=int, default=1883)
    args = parser.parse_args()

    sim = PedestalSimulator(
        pedestal_id=args.pedestal_id,
        broker_host=args.broker_host,
        broker_port=args.broker_port,
    )

    def _handle_signal(sig, frame):
        sim.stop()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    sim.run()


if __name__ == "__main__":
    main()
