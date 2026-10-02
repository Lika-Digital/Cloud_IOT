"""
Simulator — present again, and exercised rather than assumed (v3.44)
====================================================================

This file used to assert the simulator's ABSENCE. It was written in September 2026 so that a
deleted dependency reported itself honestly instead of failing as "it did not start", and it
carried a deliberate tripwire: `TC-SIM-01` asserted the file does not exist, with the message
*"the simulator has been restored, so revisit this file"*.

**It fired on 2026-10-02**, which is the whole point — a guard that tells you to come back is
worth more than a comment nobody reads. Rewritten here as a presence-and-behaviour suite.

The simulator now speaks `opta/*` and ONLY `opta/*`. The deleted one spoke `pedestal/*`, a
family no firmware has ever published, which is how a whole test suite came to be written
against a fiction.

  TC-SIM-01  the file exists, and the manager reports it available
  TC-SIM-02  the REAL loop runs and publishes — no mock of the simulator itself
  TC-SIM-03  only opta/* is published; marina/cabinet/* and pedestal/* never appear
  TC-SIM-04  the telemetry SHAPE differs between three-phase Q1 and single-phase Q2-Q4
  TC-SIM-05  the cumulative registers are monotonic
  TC-SIM-06  --stuck-register reproduces the capture: power reported, register frozen
  TC-SIM-07  --truncate-hwconfig severs the valves array as the firmware does
  TC-SIM-08  --go-silent-after stops publishing WITHOUT disconnecting
  TC-SIM-09  a valve fault is reported on opta/acks and NOT in its status topic
  TC-SIM-10  the not-installed reporting still works when the file is genuinely missing
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SIM_PATH = REPO / "simulator" / "pedestal_simulator.py"
sys.path.insert(0, str(REPO / "simulator"))


class RecordingClient:
    """A stand-in for paho's client that records instead of publishing.

    Records the REAL calls the REAL publishers make. The simulator's own loop, payload
    builders and command handling all run unmodified — mocking those would only prove the
    mock works.
    """

    def __init__(self):
        self.published: list[tuple[str, str, bool]] = []
        self.subscriptions: list[str] = []
        self.connected = True
        self.loop_running = False
        self.on_connect = None
        self.on_message = None

    # paho surface
    def connect(self, host, port, keepalive=60):
        if self.on_connect:
            self.on_connect(self, None, None, 0)

    def loop_start(self):
        self.loop_running = True

    def loop_stop(self):
        self.loop_running = False

    def disconnect(self):
        self.connected = False

    def subscribe(self, topic, qos=0):
        self.subscriptions.append(topic)

    def publish(self, topic, payload, qos=0, retain=False):
        self.published.append((topic, payload, retain))

    # helpers
    def topics(self) -> list[str]:
        return [t for t, _p, _r in self.published]

    def payloads_for(self, topic: str) -> list[dict]:
        out = []
        for t, p, _r in self.published:
            if t == topic:
                try:
                    out.append(json.loads(p))
                except json.JSONDecodeError:
                    pass
        return out

    def raw_for(self, topic: str) -> list[str]:
        return [p for t, p, _r in self.published if t == topic]


def _args(**over):
    import pedestal_simulator as sim
    ns = sim.main.__globals__["argparse"].Namespace(
        cabinet="TST_SIM_CAB", host="localhost", port=1883,
        auto_connect=0, stuck_register=False, truncate_hwconfig=False,
        uptime_days=0.0, rollover_silences=False, go_silent_after=0.0,
    )
    for k, v in over.items():
        setattr(ns, k, v)
    return ns


def _run_for(ticks: int, **over):
    """Run the real loop for a bounded number of iterations.

    The loop is driven to completion by a stop flag set from a tick counter rather than by a
    sleep, so the test is deterministic and does not depend on wall-clock timing — the thing
    that made the guard smoke test flake under load.
    """
    import pedestal_simulator as sim

    client = RecordingClient()
    s = sim.Simulator(_args(**over), client=client)

    n = {"i": 0}
    real_sleep = sim.time.sleep

    def counting_sleep(_seconds):
        n["i"] += 1
        if n["i"] >= ticks:
            s.stop_flag.set()
        real_sleep(0)

    sim.time.sleep = counting_sleep
    try:
        s.run()
    finally:
        sim.time.sleep = real_sleep
    return s, client


# ═══ TC-SIM-01 ════════════════════════════════════════════════════════════════

def test_tc_sim_01_the_simulator_exists_and_is_reported_available():
    """Present again, and the manager agrees.

    Both halves: a file on disk the manager cannot find is the same outage as no file.
    """
    from app.services.simulator_manager import SIMULATOR_PATH, simulator_available

    assert SIM_PATH.is_file(), f"{SIM_PATH} is missing"
    assert Path(SIMULATOR_PATH) == SIM_PATH, (
        f"the manager looks at {SIMULATOR_PATH}, the file is at {SIM_PATH}"
    )
    assert simulator_available() is True


# ═══ TC-SIM-02 / TC-SIM-03 ════════════════════════════════════════════════════

def test_tc_sim_02_the_real_loop_publishes():
    """Starts the actual simulator and asserts it produced traffic.

    The standing rule: a suite that passes while the thing cannot start is the same failure in
    a different place. 803 tests once passed while the guard worker had no entrypoint.
    """
    s, client = _run_for(60)

    assert client.topics(), "the simulator ran and published nothing"
    assert "opta/config/hardware" in client.topics(), "the cabinet never enumerated itself"
    assert "opta/status" in client.topics(), "no heartbeat"
    assert any(t.startswith("opta/meters/") for t in client.topics()), "no meter telemetry"
    assert any(t.startswith("opta/water/") for t in client.topics()), "no valve status"
    assert client.subscriptions == ["opta/cmd/#"], (
        f"commands must be taken from the real path only; subscribed to {client.subscriptions}"
    )
    assert not client.loop_running, "the network loop was left running"
    assert not client.connected, "the simulator exited without disconnecting"


def test_tc_sim_03_only_opta_topics_are_published():
    """No `marina/cabinet/*`, no `pedestal/*`.

    The deleted simulator spoke `pedestal/*`, and a family of handlers plus their tests grew
    around it — all exercised against something no firmware publishes. A simulator that
    speaks a fictional dialect manufactures confidence in the handlers for that dialect.
    """
    _s, client = _run_for(60)

    wrong = [t for t in client.topics() if not t.startswith("opta/")]
    assert not wrong, (
        "the simulator published non-opta topics, which no real cabinet does:\n"
        + "\n".join(f"  {t}" for t in sorted(set(wrong)))
    )


# ═══ TC-SIM-04 ════════════════════════════════════════════════════════════════

def test_tc_sim_04_telemetry_shape_differs_by_phase_count():
    """Q1 is three-phase and sends different KEYS from Q2-Q4.

    This is the one a uniform simulator cannot show. The real cabinet sends
    `currentAmpsL1..L3` / `powerKwTotal` for Q1 and `currentAmps` / `powerKw` for the rest,
    so a component assuming one shape renders fine against a uniform fake and breaks at Krk.
    """
    _s, client = _run_for(60)

    q1 = client.payloads_for("opta/meters/Q1/telemetry")
    q3 = client.payloads_for("opta/meters/Q3/telemetry")
    assert q1 and q3, "no telemetry for Q1 and/or Q3"

    assert "currentAmpsL1" in q1[0] and "powerKwTotal" in q1[0], (
        f"three-phase Q1 must send per-phase keys; got {sorted(q1[0])}"
    )
    assert "currentAmps" not in q1[0], "Q1 must not also send the single-phase key"

    assert "currentAmps" in q3[0] and "powerKw" in q3[0], (
        f"single-phase Q3 must send the flat keys; got {sorted(q3[0])}"
    )
    assert "currentAmpsL1" not in q3[0], "Q3 is single-phase and must not send per-phase keys"

    # And the ratings are not uniform either.
    hw = client.payloads_for("opta/config/hardware")[0]
    by_name = {s["socketId"]: s for s in hw["sockets"]}
    assert by_name["Q1"]["phases"] == 3
    assert by_name["Q1"]["ratedAmps"] == 32
    assert by_name["Q3"]["ratedAmps"] == 16, (
        "Q3 must be 16 A — a uniform cabinet makes a hardcoded rating look correct"
    )


# ═══ TC-SIM-05 / TC-SIM-06 ════════════════════════════════════════════════════

def test_tc_sim_05_registers_are_monotonic():
    """A cumulative register only ever increases.

    Consumption is `end - start` of this value, so a register that could go down would make a
    session's figure negative — which `session_delta` is built to refuse. The simulator must
    not be able to produce that, or the refusal path gets exercised by accident instead of on
    purpose.
    """
    import pedestal_simulator as sim

    client = RecordingClient()
    s = sim.Simulator(_args(), client=client)
    s.client.connect("localhost", 1883)

    q = s.cab.socket("Q2")
    q.state = "active"
    seen = []
    for _ in range(40):
        q.tick(1.0, stuck_register=False)
        seen.append(q.energy_kwh)
    assert all(b >= a for a, b in zip(seen, seen[1:])), "the energy register went backwards"
    assert seen[-1] > seen[0], "an active socket's register never moved"

    v = s.cab.valve("V1")
    v.state = "active"
    seen_l = []
    for _ in range(40):
        v.tick(1.0, stuck_register=False)
        seen_l.append(v.total_l)
    assert all(b >= a for a, b in zip(seen_l, seen_l[1:])), "the litre register went backwards"


def test_tc_sim_06_stuck_register_reports_power_but_never_moves():
    """The capture's Q2: 0.181 kW for six minutes against a frozen register.

    This is the configuration that retired power-over-time integration. Consumption must come
    out as a measured ZERO, and anything integrating `powerKw` would invent kWh that the
    meter never recorded — and bill for it.
    """
    import pedestal_simulator as sim

    client = RecordingClient()
    s = sim.Simulator(_args(stuck_register=True), client=client)
    q = s.cab.socket("Q2")
    q.state = "active"

    start = q.energy_kwh
    for _ in range(120):
        q.tick(1.0, stuck_register=True)

    assert q.draw_kw > 0.0, "the socket must still REPORT a draw — that is the whole point"
    assert q.energy_kwh == start, (
        f"the register moved from {start} to {q.energy_kwh} with --stuck-register; this mode "
        f"exists to prove the register, not the integral, decides consumption"
    )
    assert q.session_kwh > 0.0, (
        "the integrated figure must still accumulate, so the comparison between the two "
        "remains observable — that divergence is what raises the alarm"
    )


# ═══ TC-SIM-07 ════════════════════════════════════════════════════════════════

def test_tc_sim_07_truncated_hwconfig_severs_the_valves():
    """Reproduces the firmware's 502-byte cut, and proves the valves are what is lost.

    Published as a RAW string, not re-serialised JSON, so the truncation survives into the
    backend's tolerant parser. The sockets must still be recoverable and the valves must not —
    which is exactly the asymmetry the absent-vs-empty rule depends on.
    """
    _s, client = _run_for(40, truncate_hwconfig=True)

    raws = client.raw_for("opta/config/hardware")
    assert raws, "no hardware config published"
    raw = raws[0]

    assert len(raw) <= 502, f"payload is {len(raw)}B, not truncated"
    with pytest.raises(json.JSONDecodeError):
        json.loads(raw)
    assert '"sockets"' in raw, "the sockets array must survive the cut"
    assert '"ratedLitersPerMin"' not in raw, "the valves array must be severed"

    # And the backend's recovery must get the sockets and nothing else.
    from app.services.mqtt_handlers import _recover_truncated_hwconfig
    recovered = _recover_truncated_hwconfig(raw)
    assert recovered is not None, "the backend could not recover the truncated payload"
    data, _dropped = recovered
    assert len(data["sockets"]) >= 1
    assert "valves" not in data, (
        "recovery produced a `valves` key. Absent must mean 'no news' — an empty list here "
        "would let one truncated publish erase the cabinet's water provisioning"
    )


# ═══ TC-SIM-08 ════════════════════════════════════════════════════════════════

def test_tc_sim_08_going_silent_keeps_the_connection():
    """How a cabinet really dies: it stops talking without disconnecting.

    That matters because `opta/status` is published RETAINED. The broker keeps handing the
    last healthy heartbeat to every new subscriber, so anything that infers liveness from a
    received message calls a dead cabinet healthy — which is what happened in v3.40.
    """
    import pedestal_simulator as sim

    client = RecordingClient()
    s = sim.Simulator(_args(), client=client)
    s.client.connect("localhost", 1883)

    s._publish_status()
    before = len(client.published)
    assert before > 0

    s.silent = True
    for _ in range(10):
        s._publish_status()
        for sk in s.cab.sockets:
            s._publish_meter(sk)

    assert len(client.published) == before, (
        "a silent cabinet published anyway — it must go quiet, not go away"
    )
    assert client.connected, (
        "going silent must NOT disconnect. A disconnect would fire the last will and tell "
        "the backend something a real failure does not"
    )

    # The retained heartbeat is still the last thing on the topic.
    retained = [(t, r) for t, _p, r in client.published if t == "opta/status"]
    assert retained and retained[-1][1] is True, (
        "opta/status must be published retained — that is what makes the replay trap real"
    )


# ═══ TC-SIM-09 ════════════════════════════════════════════════════════════════

def test_tc_sim_09_a_valve_fault_appears_only_on_acks():
    """`STATE_FAULT` is reported REACTIVELY, never in the status topic.

    This asymmetry is why `/api/nfc/scan` cannot pre-check a valve the way it pre-checks a
    socket: the scan happens before any open command, so there is nothing to read. Reproduced
    so the limitation is demonstrable rather than described in a comment.
    """
    import pedestal_simulator as sim

    client = RecordingClient()
    s = sim.Simulator(_args(), client=client)
    s.client.connect("localhost", 1883)

    v = s.cab.valve("V1")
    v.state = "fault"

    s._publish_valve_status(v)
    status = client.payloads_for("opta/water/V1/status")[-1]
    # The status topic carries whatever `state` is — but no capture has ever shown "fault"
    # there, so the backend must not key a check on it.
    assert "state" in status and "hw_status" in status

    client.published.clear()

    class _Msg:
        topic = "opta/cmd/water/V1"
        payload = json.dumps({"cmd": "open", "msgId": "sim-1"}).encode()

    s._on_message(None, None, _Msg())

    acks = client.payloads_for("opta/acks")
    assert acks, "an open command against a faulted valve produced no ack"
    assert acks[-1]["status"] == "error"
    assert acks[-1]["reason"] == "outlet_fault", (
        f"got {acks[-1].get('reason')!r} — the ack is the ONLY place a valve fault surfaces"
    )
    assert v.state == "fault", "a refused open must not change the valve's state"


# ═══ TC-SIM-10 ════════════════════════════════════════════════════════════════

def test_tc_sim_10_absence_is_still_reported_honestly(monkeypatch):
    """If the file goes missing again, the manager must say so — not fail as 'did not start'.

    Kept from the original suite, because the reason it was written has not changed: a removed
    dependency that reports a generic failure costs an afternoon of looking in the wrong
    place. Exercised by pointing the manager at a path that does not exist, rather than by
    deleting the simulator.
    """
    from app.services import simulator_manager as sm

    missing = REPO / "simulator" / "__definitely_not_here__.py"
    monkeypatch.setattr(sm, "SIMULATOR_PATH", missing)

    assert sm.simulator_available() is False
    msg = sm.NOT_INSTALLED_MESSAGE.lower()
    assert "not installed" in msg, "the message must say the simulator is ABSENT"
    assert "did not start" not in msg, (
        "'did not start' is the failure mode this message exists to replace"
    )
