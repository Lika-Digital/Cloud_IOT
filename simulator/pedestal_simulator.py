#!/usr/bin/env python3
"""Opta cabinet simulator — rewritten 2026-10-02 against the real contract.

The previous simulator was deleted in March 2026 (`be0df4f`) and spoke the `pedestal/*`
topic family, which **no firmware has ever published**. This one speaks `opta/*` and only
`opta/*`, because that is the only family a real cabinet uses — verified by a full MQTT
capture from MAR_KRK_ORM_01, firmware 3.1.0, 2026-09-29.

WHAT IT REPRODUCES, AND WHY EACH ONE IS HERE
--------------------------------------------
Every item below exists because something in the system gets it wrong when it is absent:

* **4 sockets and 2 valves (six outlets).** A four-outlet cabinet cannot exercise the
  six-tag model at all.
* **Q1 three-phase, Q2-Q4 single-phase.** The telemetry payload SHAPE differs: Q1 sends
  `currentAmpsL1..L3` / `powerKwTotal`, the others send `currentAmps` / `powerKw`. A UI that
  assumes one shape is a real defect, and with a uniform simulator it renders fine.
* **Q1/Q2 at 32 A, Q3/Q4 at 16 A.** The sockets are not identical; any load display reading
  from a constant looks correct against a uniform cabinet.
* **Valve `state` and `hw_status`.** They were published all along and persisted only from
  v3.43. A simulator that omits them cannot show the difference between `idle` and `unknown`.
* **A monotonic `energyKwh` register, and the option to freeze it.** Consumption is the
  register delta. `--stuck-register` reproduces the capture's Q2, which reported 0.181 kW for
  six minutes while its register never moved — the reason integration was abandoned.
* **`millis()` uptime as `ts`, not a wall clock.** `--uptime-days` can start near the signed
  int32 rollover that silences a real cabinet at 24.85 days.
* **Truncation of `opta/config/hardware` at ~502 bytes.** `--truncate-hwconfig` severs the
  trailing `valves` array exactly as the firmware does, so the absent-vs-empty rule can be
  exercised rather than trusted.
* **Silence.** `--go-silent-after` stops publishing without disconnecting, which is how a
  cabinet actually dies. The retained `opta/status` keeps replaying to new subscribers, so
  this is the only way to test that liveness does not come from a retained message.

WHAT IT DOES NOT DO
-------------------
No `marina/cabinet/*` (aspirational — nothing publishes it). No `pedestal/*` (legacy test
tool). No commands invented that the firmware does not accept: it subscribes to `opta/cmd/*`
and acknowledges on `opta/acks`, which is the real command path.

USAGE
    python simulator/pedestal_simulator.py --cabinet MAR_KRK_SIM_01
    python simulator/pedestal_simulator.py --help      # every switch, with its reason
"""
from __future__ import annotations

import argparse
import json
import random
import signal
import sys
import threading
import time
from dataclasses import dataclass, field

try:
    import paho.mqtt.client as mqtt
except ImportError:
    sys.exit("paho-mqtt is required:  pip install paho-mqtt")


# Signed int32 milliseconds. A real cabinet goes silent here and does not self-recover —
# confirmed on MAR_KRK_ORM_01, firmware 3.0.0, 2026-09-20. 24.85 days.
INT32_MAX_MS = 2_147_483_647

HEARTBEAT_S = 15.0        # opta/status, retained
TELEMETRY_S = 5.0         # opta/meters/Q{n}/telemetry
OUTLET_STATUS_S = 10.0    # opta/sockets/Q{n}/status and opta/water/V{n}/status


@dataclass
class Socket:
    name: str
    phases: int
    rated_amps: float
    modbus: int
    meter_type: str
    state: str = "idle"            # idle | active | fault
    hw_status: str = "off"
    connected: bool = False        # the plug-in signal; valves have no equivalent
    energy_kwh: float = 0.0        # MONOTONIC cumulative register
    session_kwh: float = 0.0
    draw_kw: float = 0.0

    def tick(self, dt: float, *, stuck_register: bool) -> None:
        if self.state != "active":
            self.draw_kw = 0.0
            return
        # A plausible load for the rating, wandering slowly.
        target = min(self.rated_amps * 230.0 * (0.9 if self.phases == 1 else 2.6) / 1000.0, 7.0)
        self.draw_kw = max(0.2, min(target, self.draw_kw + random.uniform(-0.25, 0.25) or 1.8))
        gained = self.draw_kw * (dt / 3600.0)
        self.session_kwh += gained
        if not stuck_register:
            # The register only ever increases. Nothing in the system may rely on it
            # decreasing, and a simulator that let it would hide a real defect.
            self.energy_kwh += gained


@dataclass
class Valve:
    name: str
    rated_lpm: float
    state: str = "idle"            # idle | active — NO "pending": there is no hose sensor
    hw_status: str = "off"
    total_l: float = 0.0           # MONOTONIC cumulative register
    session_l: float = 0.0
    lpm: float = 0.0

    def tick(self, dt: float, *, stuck_register: bool) -> None:
        if self.state != "active":
            self.lpm = 0.0
            return
        self.lpm = max(1.0, min(self.rated_lpm, self.lpm + random.uniform(-1.5, 1.5) or 12.0))
        gained = self.lpm * (dt / 60.0)
        self.session_l += gained
        if not stuck_register:
            self.total_l += gained


@dataclass
class Cabinet:
    cabinet_id: str
    firmware: str = "3.1.0"
    uptime_ms: int = 0
    door: str = "closed"
    temperature_c: float = 22.0
    moisture_pct: float = 35.0
    sockets: list[Socket] = field(default_factory=list)
    valves: list[Valve] = field(default_factory=list)

    @classmethod
    def krk(cls, cabinet_id: str) -> "Cabinet":
        """The MAR_KRK_ORM_01 layout, from its own `opta/config/hardware`.

        Not four identical sockets, which is the point: Q1 is three-phase at 32 A with a
        different meter, Q3 and Q4 are 16 A.
        """
        return cls(
            cabinet_id=cabinet_id,
            sockets=[
                Socket("Q1", phases=3, rated_amps=32, modbus=1, meter_type="ABB D13 15-M 65"),
                Socket("Q2", phases=1, rated_amps=32, modbus=2, meter_type="ABB D11 15-M 40"),
                Socket("Q3", phases=1, rated_amps=16, modbus=3, meter_type="ABB D11 15-M 40"),
                Socket("Q4", phases=1, rated_amps=16, modbus=4, meter_type="ABB D11 15-M 40"),
            ],
            valves=[Valve("V1", rated_lpm=20.0), Valve("V2", rated_lpm=20.0)],
        )

    def socket(self, name: str) -> Socket | None:
        return next((s for s in self.sockets if s.name == name), None)

    def valve(self, name: str) -> Valve | None:
        return next((v for v in self.valves if v.name == name), None)


class Simulator:
    def __init__(self, args: argparse.Namespace, *, client=None):
        """`client` is an injection seam, for the same reason the guard worker has one.

        A simulator that can only be exercised against a live broker gets exercised by hand,
        which means it gets exercised when someone remembers. With the seam, the smoke test
        runs the REAL loop and the REAL publishers against a recording client and asserts the
        topics and payload shapes — no mock of the simulator itself, which would only prove
        the mock works.
        """
        self.args = args
        self.cab = Cabinet.krk(args.cabinet)
        self.cab.uptime_ms = int(args.uptime_days * 86_400_000)
        self.started = time.monotonic()
        self.silent = False
        self.stop_flag = threading.Event()
        self.client = client if client is not None else mqtt.Client(
            client_id=f"sim-{args.cabinet}")
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

    # ── MQTT ──────────────────────────────────────────────────────────────────

    def _on_connect(self, client, _u, _f, rc):
        if rc != 0:
            print(f"[sim] connect failed rc={rc}", file=sys.stderr)
            return
        print(f"[sim] connected to {self.args.host}:{self.args.port} as {self.args.cabinet}")
        # The real command path. Nothing else is accepted, because nothing else exists.
        client.subscribe("opta/cmd/#", qos=1)
        self._publish_hwconfig()

    def _pub(self, topic: str, payload: dict, *, retain: bool = False) -> None:
        """Publish, unless we are pretending to be dead.

        While silent, nothing is published AND the connection is kept. That is how a cabinet
        actually fails — and because `opta/status` was published retained, the broker keeps
        handing the last healthy one to every new subscriber. Anything inferring liveness
        from a received message will believe this cabinet is fine for ever.
        """
        if self.silent:
            return
        self.client.publish(topic, json.dumps(payload), qos=0, retain=retain)

    def _ts(self) -> int:
        """`millis()` uptime, NOT a wall clock — exactly what the firmware sends.

        Wraps at signed int32. A real cabinet stops publishing entirely at this point and
        needs a power cycle; `--rollover-silences` reproduces that.
        """
        ms = self.cab.uptime_ms + int((time.monotonic() - self.started) * 1000)
        if ms > INT32_MAX_MS:
            if self.args.rollover_silences and not self.silent:
                print(f"[sim] millis() rolled over at {ms} — going silent, as the real "
                      f"cabinet does. It will NOT recover.", file=sys.stderr)
                self.silent = True
            ms = -(ms & INT32_MAX_MS)       # the signed wrap, negative as the firmware shows
        return ms

    # ── Publishers ────────────────────────────────────────────────────────────

    def _publish_hwconfig(self) -> None:
        """`opta/config/hardware` — one shot, enumerating the cabinet.

        NOT retained, matching the firmware. That is a real limitation: a late subscriber
        waits for a cabinet restart to learn what the cabinet has, which is why
        `/api/nfc/outlets` has to report whether it ever heard this message.
        """
        payload = {
            "cabinetId": self.cab.cabinet_id,
            "firmwareVersion": self.cab.firmware,
            "sockets": [
                {"socketId": s.name, "meterType": s.meter_type, "phases": s.phases,
                 "ratedAmps": s.rated_amps, "modbusAddress": s.modbus}
                for s in self.cab.sockets
            ],
            "valves": [
                {"valveId": v.name, "ratedLitersPerMin": v.rated_lpm} for v in self.cab.valves
            ],
        }
        raw = json.dumps(payload)
        if self.args.truncate_hwconfig:
            # The firmware's MQTT publish buffer cuts this at ~502 bytes, severing the
            # trailing `valves` array. Published as a RAW string so the truncation survives
            # into the handler — the backend's tolerant parser recovers the sockets and loses
            # the valves, and an ABSENT valves key must mean "no news", never "no valves".
            cut = raw[:502]
            print(f"[sim] publishing TRUNCATED hwconfig: {len(raw)}B -> {len(cut)}B "
                  f"(valves array severed, as firmware 2.4.0/2.5.0 does)")
            self.client.publish("opta/config/hardware", cut, qos=0, retain=False)
            return
        self._pub("opta/config/hardware", payload)

    def _publish_status(self) -> None:
        """`opta/status` — RETAINED, every 15 s. The heartbeat."""
        self._pub("opta/status", {
            "cabinetId": self.cab.cabinet_id,
            "firmwareVersion": self.cab.firmware,
            "ts": self._ts(),
            "uptimeMs": self.cab.uptime_ms,
            "temperature": round(self.cab.temperature_c, 1),
            "moisture": round(self.cab.moisture_pct, 1),
        }, retain=True)

    def _publish_socket_status(self, s: Socket) -> None:
        self._pub(f"opta/sockets/{s.name}/status", {
            "id": s.name,
            "cabinetId": self.cab.cabinet_id,
            "state": s.state,
            "hw_status": s.hw_status,
            "connected": s.connected,
            "ts": self._ts(),
            "energyKwh": round(s.energy_kwh, 4),
            "sessionKwh": round(s.session_kwh, 4),
            "session": None,
        })

    def _publish_meter(self, s: Socket) -> None:
        """`opta/meters/Q{n}/telemetry` — THE SHAPE DIFFERS BY SOCKET.

        Three-phase sends `currentAmpsL1..L3` and `powerKwTotal`; single-phase sends
        `currentAmps` and `powerKw`. A consumer that assumes one shape is a defect, and a
        uniform simulator would never show it.
        """
        base = {
            "id": s.name,
            "cabinetId": self.cab.cabinet_id,
            "ts": self._ts(),
            "voltage": round(random.uniform(228.0, 234.0), 1),
            "energyKwh": round(s.energy_kwh, 4),
            "powerFactor": round(random.uniform(0.92, 0.99), 2),
        }
        if s.phases == 3:
            per = s.draw_kw / 3.0
            amps = (per * 1000.0) / 230.0 if per else 0.0
            base.update({
                "currentAmpsL1": round(amps * random.uniform(0.95, 1.05), 2),
                "currentAmpsL2": round(amps * random.uniform(0.95, 1.05), 2),
                "currentAmpsL3": round(amps * random.uniform(0.95, 1.05), 2),
                "powerKwTotal": round(s.draw_kw, 3),
            })
        else:
            base.update({
                "currentAmps": round((s.draw_kw * 1000.0) / 230.0, 2),
                "powerKw": round(s.draw_kw, 3),
            })
        self._pub(f"opta/meters/{s.name}/telemetry", base)

    def _publish_valve_status(self, v: Valve) -> None:
        """`opta/water/V{n}/status` — carries `state` AND `hw_status`.

        Both were in the real payload all along and were broadcast-and-discarded until
        v3.43. A simulator that omitted them could not show the difference between a valve
        reporting `idle` and one nobody has heard from, which is `unknown`.
        """
        self._pub(f"opta/water/{v.name}/status", {
            "id": v.name,
            "cabinetId": self.cab.cabinet_id,
            "state": v.state,
            "hw_status": v.hw_status,
            "ts": self._ts(),
            "total_l": round(v.total_l, 3),
            "session_l": round(v.session_l, 3),
            "session": None,
        })

    def _publish_event(self, event: str, **data) -> None:
        self._pub("opta/events", {
            "cabinetId": self.cab.cabinet_id, "event": event,
            "ts": self._ts(), **data,
        })

    def _ack(self, req_id: str | None, status: str, reason: str | None = None) -> None:
        payload = {"cabinetId": self.cab.cabinet_id, "status": status, "ts": self._ts()}
        if req_id:
            payload["req_id"] = req_id
        if reason:
            payload["reason"] = reason
        self._pub("opta/acks", payload)

    # ── Commands ──────────────────────────────────────────────────────────────

    def _on_message(self, _c, _u, msg) -> None:
        """`opta/cmd/socket/Q{n}` and `opta/cmd/water/V{n}`.

        A faulted valve answers on `opta/acks` with `outlet_fault` and NOT in its status
        topic, which is why `/api/nfc/scan` cannot pre-check a valve the way it pre-checks a
        socket. Reproduced here so that asymmetry is visible rather than described.
        """
        topic = msg.topic
        try:
            body = json.loads(msg.payload.decode() or "{}")
        except json.JSONDecodeError:
            self._ack(None, "error", "bad_payload")
            return
        cmd = (body.get("cmd") or body.get("command") or "").lower()
        req_id = body.get("msgId") or body.get("req_id")

        parts = topic.split("/")
        if len(parts) < 4:
            self._ack(req_id, "error", "unknown_topic")
            return
        kind, name = parts[2], parts[3]

        if kind == "socket":
            s = self.cab.socket(name)
            if s is None:
                self._ack(req_id, "error", "unknown_outlet")
                return
            if s.state == "fault":
                self._ack(req_id, "error", "outlet_fault")
                return
            if cmd in ("enable", "activate", "on"):
                s.state, s.hw_status, s.session_kwh = "active", "on", 0.0
                self._ack(req_id, "ok")
                self._publish_event("OutletActivated", outletId=name)
            elif cmd in ("disable", "stop", "off"):
                s.state, s.hw_status = "idle", "off"
                self._ack(req_id, "ok")
                self._publish_event("SessionEnded", outletId=name,
                                    sessionKwh=round(s.session_kwh, 4),
                                    energyKwh=round(s.energy_kwh, 4))
            else:
                self._ack(req_id, "error", "unknown_cmd")
            self._publish_socket_status(s)

        elif kind == "water":
            v = self.cab.valve(name)
            if v is None:
                self._ack(req_id, "error", "unknown_outlet")
                return
            if v.state == "fault":
                # The ONLY place a valve fault is observable.
                self._ack(req_id, "error", "outlet_fault")
                return
            if cmd in ("enable", "activate", "on", "open"):
                v.state, v.hw_status, v.session_l = "active", "on", 0.0
                self._ack(req_id, "ok")
                self._publish_event("OutletActivated", outletId=name)
            elif cmd in ("disable", "stop", "off", "close"):
                v.state, v.hw_status = "idle", "off"
                self._ack(req_id, "ok")
                self._publish_event("SessionEnded", outletId=name,
                                    sessionLiters=round(v.session_l, 3),
                                    totalLiters=round(v.total_l, 3))
            else:
                self._ack(req_id, "error", "unknown_cmd")
            self._publish_valve_status(v)
        else:
            self._ack(req_id, "ok")

    # ── Loop ──────────────────────────────────────────────────────────────────

    def run(self) -> int:
        self.client.connect(self.args.host, self.args.port, keepalive=30)
        self.client.loop_start()

        if self.args.auto_connect:
            for s in self.cab.sockets[:self.args.auto_connect]:
                s.connected = True
                self._publish_event("UserPluggedIn", outletId=s.name)
                print(f"[sim] {s.name}: plugged in")

        last = time.monotonic()
        next_status = next_outlet = next_meter = 0.0
        silent_at = (time.monotonic() + self.args.go_silent_after
                     if self.args.go_silent_after else None)

        try:
            while not self.stop_flag.is_set():
                now = time.monotonic()
                dt = now - last
                last = now

                if silent_at and now >= silent_at and not self.silent:
                    print("[sim] GOING SILENT — connection stays up, publishing stops. The "
                          "retained opta/status keeps replaying to new subscribers.",
                          file=sys.stderr)
                    self.silent = True

                for s in self.cab.sockets:
                    s.tick(dt, stuck_register=self.args.stuck_register)
                for v in self.cab.valves:
                    v.tick(dt, stuck_register=self.args.stuck_register)

                self.cab.temperature_c = max(
                    5.0, min(75.0, self.cab.temperature_c + random.uniform(-0.3, 0.3)))
                self.cab.moisture_pct = max(
                    0.0, min(100.0, self.cab.moisture_pct + random.uniform(-0.6, 0.6)))

                if now >= next_status:
                    self._publish_status()
                    next_status = now + HEARTBEAT_S
                if now >= next_outlet:
                    for s in self.cab.sockets:
                        self._publish_socket_status(s)
                    for v in self.cab.valves:
                        self._publish_valve_status(v)
                    next_outlet = now + OUTLET_STATUS_S
                if now >= next_meter:
                    for s in self.cab.sockets:
                        self._publish_meter(s)
                    next_meter = now + TELEMETRY_S

                time.sleep(0.25)
        finally:
            self.client.loop_stop()
            self.client.disconnect()
        return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Opta cabinet simulator — opta/* topics only.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--cabinet", default="MAR_KRK_SIM_01", help="cabinetId to publish as")
    p.add_argument("--host", default="localhost")
    p.add_argument("--port", type=int, default=1883)
    p.add_argument("--auto-connect", type=int, default=0, metavar="N",
                   help="mark the first N sockets physically plugged in on start. Default 0 — "
                        "a cabinet nobody has plugged into is the honest starting state, and "
                        "the deleted simulator's auto-connect hid activation bugs")
    p.add_argument("--stuck-register", action="store_true",
                   help="report power draw while the cumulative register NEVER MOVES. This is "
                        "the capture's Q2: 0.181 kW for six minutes against a frozen register. "
                        "Consumption must come out as zero, not as the integral")
    p.add_argument("--truncate-hwconfig", action="store_true",
                   help="cut opta/config/hardware at 502 bytes, severing the valves array, as "
                        "firmware 2.4.0/2.5.0 does. An ABSENT valves key must mean 'no news'")
    p.add_argument("--uptime-days", type=float, default=0.0, metavar="D",
                   help="start with D days of uptime. Use 24.8 to sit just before the signed "
                        "int32 millis() rollover that silences a real cabinet at 24.85 days")
    p.add_argument("--rollover-silences", action="store_true",
                   help="go silent when millis() wraps, as the real cabinet does. It does not "
                        "recover; a power cycle is required")
    p.add_argument("--go-silent-after", type=float, default=0.0, metavar="S",
                   help="stop publishing after S seconds WITHOUT disconnecting — how a cabinet "
                        "really dies. The retained opta/status keeps replaying, so anything "
                        "inferring liveness from a received message will still call it healthy")
    args = p.parse_args(argv)

    sim = Simulator(args)

    def _stop(_sig, _frm):
        print("\n[sim] stopping")
        sim.stop_flag.set()

    signal.signal(signal.SIGINT, _stop)
    try:
        signal.signal(signal.SIGTERM, _stop)
    except (AttributeError, ValueError):
        pass
    return sim.run()


if __name__ == "__main__":
    sys.exit(main())
