#!/usr/bin/env python3
"""
Pedestal Simulator — simulates one or more Arduino Opta pedestals over MQTT.

Each pedestal has 4 electricity sockets + 1 water meter.
Session flow per socket:
  1. Random plug-in  → publish "connected"   → session becomes pending in backend
  2. Backend "allow" → send power readings for 2-10 min
  3. Time expires    → publish "disconnected" → session completed
  4. Backend "deny"/"stop" → immediately disconnect

Usage:
  python pedestal_simulator.py --pedestal-ids 1,2,3 --broker-host localhost --broker-port 1883
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
from generators import (
    PowerGenerator, WaterGenerator, SocketStateManager, WaterStateManager,
    TemperatureGenerator, MoistureGenerator,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [SIM] %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

TICK_INTERVAL      = 0.5
POWER_INTERVAL     = 2.0
WATER_INTERVAL     = 2.0
HEARTBEAT_INTERVAL = 10.0
SENSOR_INTERVAL    = 15.0

SOCKET_CONTROL_RE = re.compile(r"pedestal/(\d+)/socket/(\d+)/control")
WATER_CONTROL_RE  = re.compile(r"pedestal/(\d+)/water/control")


class VirtualPedestal:
    """All state machines and generators for one physical pedestal."""

    def __init__(self, pedestal_id: int):
        self.pedestal_id = pedestal_id
        self.socket_states    = [SocketStateManager(i + 1) for i in range(4)]
        self.water_state      = WaterStateManager()
        self.power_generators = [PowerGenerator(i + 1) for i in range(4)]
        self.water_generator  = WaterGenerator()
        self.temp_generator   = TemperatureGenerator()
        self.moist_generator  = MoistureGenerator()
        self.last_power_time  = 0.0
        self.last_water_time  = 0.0
        self.last_heartbeat   = 0.0
        self.last_sensor_time = 0.0


class PedestalSimulator:
    def __init__(self, pedestal_ids: list[int], broker_host: str, broker_port: int):
        self.broker_host = broker_host
        self.broker_port = broker_port
        self._running    = False

        self._pedestals: dict[int, VirtualPedestal] = {
            pid: VirtualPedestal(pid) for pid in pedestal_ids
        }
        logger.info(f"Simulating {len(pedestal_ids)} pedestal(s): {pedestal_ids}")

        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self._client.on_connect    = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message    = self._on_message

    # ─── MQTT helpers ─────────────────────────────────────────────────────────

    def _pub(self, topic: str, payload):
        if isinstance(payload, dict):
            payload = json.dumps(payload)
        self._client.publish(topic, payload, qos=1)
        logger.debug(f"→ {topic}: {payload}")

    # ─── MQTT callbacks ───────────────────────────────────────────────────────

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            logger.info(f"Connected to {self.broker_host}:{self.broker_port}")
            for pid in self._pedestals:
                client.subscribe(f"pedestal/{pid}/socket/+/control", qos=1)
                client.subscribe(f"pedestal/{pid}/water/control", qos=1)
            # Publish initial sensor readings immediately on connect
            for pid, vp in self._pedestals.items():
                vp.last_sensor_time = 0.0  # triggers publish on first tick
            logger.info("Subscribed to all control topics")
        else:
            logger.error(f"Connection failed: {reason_code}")

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        logger.warning(f"Disconnected from broker (reason: {reason_code})")

    def _on_message(self, client, userdata, msg):
        command = msg.payload.decode("utf-8").strip().strip('"')
        topic   = msg.topic

        if m := SOCKET_CONTROL_RE.match(topic):
            pid, socket_id = int(m.group(1)), int(m.group(2))
            vp = self._pedestals.get(pid)
            if vp:
                mgr = next((s for s in vp.socket_states if s.socket_id == socket_id), None)
                if mgr:
                    mgr.on_control(command)
                    if command in ("deny", "stop"):
                        self._pub(f"pedestal/{pid}/socket/{socket_id}/status", '"disconnected"')
                        logger.info(f"P{pid} Socket {socket_id}: {command} → disconnected")

        elif m := WATER_CONTROL_RE.match(topic):
            pid = int(m.group(1))
            vp  = self._pedestals.get(pid)
            if vp:
                vp.water_state.on_control(command)
                logger.info(f"P{pid} Water: {command}")

    # ─── Main loop ────────────────────────────────────────────────────────────

    def run(self):
        self._running = True

        try:
            self._client.connect(self.broker_host, self.broker_port, keepalive=60)
        except Exception as e:
            logger.error(f"Cannot connect to broker: {e}")
            sys.exit(1)

        self._client.loop_start()
        time.sleep(1.5)

        try:
            while self._running:
                now = time.time()

                for pid, vp in self._pedestals.items():

                    # ── Socket state machine ticks ─────────────────────────
                    for mgr in vp.socket_states:
                        event = mgr.tick()
                        if event == "connected":
                            logger.info(f"P{pid} Socket {mgr.socket_id}: plug-in → pending")
                            self._pub(f"pedestal/{pid}/socket/{mgr.socket_id}/status", '"connected"')
                        elif event == "disconnected":
                            logger.info(f"P{pid} Socket {mgr.socket_id}: unplugged → done")
                            self._pub(f"pedestal/{pid}/socket/{mgr.socket_id}/status", '"disconnected"')

                    # ── Water state machine tick ───────────────────────────
                    water_event = vp.water_state.tick()
                    if water_event == "start":
                        logger.info(f"P{pid} Water: flow detected → pending")
                    elif water_event == "stop":
                        logger.info(f"P{pid} Water: flow stopped → done")

                    # ── Power readings (active sockets only) ──────────────
                    if now - vp.last_power_time >= POWER_INTERVAL:
                        vp.last_power_time = now
                        for i, mgr in enumerate(vp.socket_states):
                            if mgr.is_active:
                                reading = vp.power_generators[i].next_reading()
                                self._pub(f"pedestal/{pid}/socket/{mgr.socket_id}/power", reading)

                    # ── Water readings ─────────────────────────────────────
                    if now - vp.last_water_time >= WATER_INTERVAL:
                        vp.last_water_time = now
                        if vp.water_state.is_flowing:
                            reading = vp.water_generator.next_reading(flowing=True)
                            self._pub(f"pedestal/{pid}/water/flow", reading)
                        elif water_event == "stop":
                            reading = vp.water_generator.next_reading(flowing=False)
                            self._pub(f"pedestal/{pid}/water/flow", reading)

                    # ── Heartbeat ──────────────────────────────────────────
                    if now - vp.last_heartbeat >= HEARTBEAT_INTERVAL:
                        vp.last_heartbeat = now
                        self._pub(f"pedestal/{pid}/heartbeat", {
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "online": True,
                        })

                    # ── Temperature & Moisture sensors ─────────────────────
                    if now - vp.last_sensor_time >= SENSOR_INTERVAL:
                        vp.last_sensor_time = now
                        active_count = sum(1 for s in vp.socket_states if s.is_active)
                        water_active = vp.water_state.is_active
                        self._pub(
                            f"pedestal/{pid}/sensors/temperature",
                            vp.temp_generator.next_reading(active_count),
                        )
                        self._pub(
                            f"pedestal/{pid}/sensors/moisture",
                            vp.moist_generator.next_reading(water_active),
                        )

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
    parser = argparse.ArgumentParser(description="Multi-pedestal MQTT Simulator")
    parser.add_argument("--pedestal-ids",  type=str, default="1",
                        help="Comma-separated pedestal IDs, e.g. 1,2,3")
    parser.add_argument("--broker-host",   type=str, default="localhost")
    parser.add_argument("--broker-port",   type=int, default=1883)
    args = parser.parse_args()

    pedestal_ids = [int(x.strip()) for x in args.pedestal_ids.split(",") if x.strip()]

    sim = PedestalSimulator(pedestal_ids, args.broker_host, args.broker_port)

    def _handle_signal(sig, frame):
        sim.stop()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT,  _handle_signal)

    sim.run()


if __name__ == "__main__":
    main()
