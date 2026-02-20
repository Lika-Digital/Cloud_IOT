#!/usr/bin/env python3
"""
Pedestal Simulator — simulates an Arduino Opta pedestal over MQTT.

Session flow per socket:
  1. Random plug-in → publish "connected" → session becomes pending
  2. Backend sends "allow" → start power readings for 2-10 min
  3. Time expires (or "stop" received) → publish "disconnected" → session completed

Usage:
  python pedestal_simulator.py --pedestal-id 1 --broker-host localhost --broker-port 1883
"""
import argparse
import json
import logging
import re
import signal
import sys
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

sys.path.insert(0, str(__file__).replace("pedestal_simulator.py", ""))
from generators import PowerGenerator, WaterGenerator, SocketStateManager, WaterStateManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [SIM] %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

TICK_INTERVAL = 0.5     # seconds between state machine ticks
POWER_INTERVAL = 2.0    # seconds between power readings (when active)
WATER_INTERVAL = 2.0    # seconds between water readings (when flowing)
HEARTBEAT_INTERVAL = 10.0

SOCKET_CONTROL_RE = re.compile(r"pedestal/(\d+)/socket/(\d+)/control")
WATER_CONTROL_RE  = re.compile(r"pedestal/(\d+)/water/control")


class PedestalSimulator:
    def __init__(self, pedestal_id: int, broker_host: str, broker_port: int):
        self.pedestal_id = pedestal_id
        self.broker_host = broker_host
        self.broker_port = broker_port
        self._running = False

        # State machines (one per socket + water)
        self._socket_states   = [SocketStateManager(i + 1) for i in range(4)]
        self._water_state     = WaterStateManager()

        # Data generators
        self._power_generators = [PowerGenerator(i + 1) for i in range(4)]
        self._water_generator  = WaterGenerator()

        # MQTT client
        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self._client.on_connect    = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message    = self._on_message

        # Timing
        self._last_power_time     = 0.0
        self._last_water_time     = 0.0
        self._last_heartbeat_time = 0.0

    # ─── MQTT helpers ─────────────────────────────────────────────────────────

    def _topic(self, suffix: str) -> str:
        return f"pedestal/{self.pedestal_id}/{suffix}"

    def _publish(self, topic: str, payload):
        if isinstance(payload, dict):
            payload = json.dumps(payload)
        self._client.publish(topic, payload, qos=1)
        logger.debug(f"→ {topic}: {payload}")

    # ─── MQTT callbacks ───────────────────────────────────────────────────────

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            logger.info(f"Connected to broker {self.broker_host}:{self.broker_port}")
            client.subscribe(self._topic("socket/+/control"), qos=1)
            client.subscribe(self._topic("water/control"), qos=1)
            logger.info("Subscribed to control topics")
        else:
            logger.error(f"Connection failed: {reason_code}")

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        logger.warning(f"Disconnected from broker (reason: {reason_code})")

    def _on_message(self, client, userdata, msg):
        command = msg.payload.decode("utf-8").strip().strip('"')
        topic   = msg.topic
        logger.info(f"← Control: {topic} = {command}")

        if m := SOCKET_CONTROL_RE.match(topic):
            socket_id = int(m.group(2))
            mgr = next((s for s in self._socket_states if s.socket_id == socket_id), None)
            if mgr:
                mgr.on_control(command)
                if command in ("deny", "stop"):
                    self._publish(self._topic(f"socket/{socket_id}/status"), '"disconnected"')

        elif WATER_CONTROL_RE.match(topic):
            self._water_state.on_control(command)

    # ─── Main loop ────────────────────────────────────────────────────────────

    def run(self):
        self._running = True
        logger.info(f"Starting simulator for pedestal {self.pedestal_id}")

        try:
            self._client.connect(self.broker_host, self.broker_port, keepalive=60)
        except Exception as e:
            logger.error(f"Cannot connect to broker: {e}")
            sys.exit(1)

        self._client.loop_start()
        time.sleep(1.5)  # wait for broker handshake

        try:
            while self._running:
                now = time.time()

                # ── Socket state machine ticks ─────────────────────────────
                for mgr in self._socket_states:
                    event = mgr.tick()
                    if event == "connected":
                        logger.info(f"Socket {mgr.socket_id}: plug-in detected → pending")
                        self._publish(
                            self._topic(f"socket/{mgr.socket_id}/status"),
                            '"connected"'
                        )
                    elif event == "disconnected":
                        logger.info(f"Socket {mgr.socket_id}: unplugged → session ended")
                        self._publish(
                            self._topic(f"socket/{mgr.socket_id}/status"),
                            '"disconnected"'
                        )

                # ── Water state machine tick ───────────────────────────────
                water_event = self._water_state.tick()
                if water_event == "start":
                    logger.info("Water: flow detected → pending")
                elif water_event == "stop":
                    logger.info("Water: flow stopped → session ended")

                # ── Power readings (active sockets only) ──────────────────
                if now - self._last_power_time >= POWER_INTERVAL:
                    self._last_power_time = now
                    for i, mgr in enumerate(self._socket_states):
                        if mgr.is_active:
                            reading = self._power_generators[i].next_reading()
                            self._publish(
                                self._topic(f"socket/{mgr.socket_id}/power"),
                                reading
                            )

                # ── Water readings (flowing = pending or active) ───────────
                if now - self._last_water_time >= WATER_INTERVAL:
                    self._last_water_time = now
                    if self._water_state.is_flowing:
                        reading = self._water_generator.next_reading(flowing=True)
                        self._publish(self._topic("water/flow"), reading)
                    elif water_event == "stop":
                        # Send one final zero-flow reading
                        reading = self._water_generator.next_reading(flowing=False)
                        self._publish(self._topic("water/flow"), reading)

                # ── Heartbeat ─────────────────────────────────────────────
                if now - self._last_heartbeat_time >= HEARTBEAT_INTERVAL:
                    self._last_heartbeat_time = now
                    self._publish(self._topic("heartbeat"), {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "online": True,
                    })

                time.sleep(TICK_INTERVAL)

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
    parser.add_argument("--pedestal-id",  type=int, default=1)
    parser.add_argument("--broker-host",  type=str, default="localhost")
    parser.add_argument("--broker-port",  type=int, default=1883)
    args = parser.parse_args()

    sim = PedestalSimulator(args.pedestal_id, args.broker_host, args.broker_port)

    def _handle_signal(sig, frame):
        sim.stop()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT,  _handle_signal)

    sim.run()


if __name__ == "__main__":
    main()
