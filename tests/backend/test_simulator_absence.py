"""
The simulator is missing, and says so (v3.43)
============================================

`simulator/pedestal_simulator.py` was deleted on 2026-03-15 by `be0df4f`
("fix(nuc-image): remove simulator…"), which removed 480 lines across two files. The stated
reason was "not needed on NUC" — but it left the repository entirely rather than being excluded
from the NUC image, and `simulator_manager` was left pointing at the deleted path.

`Popen` on a missing file raises `FileNotFoundError`, which was caught and logged. So
**"Start Simulator" failed silently into the error log for six months**, and the dashboard
answered `running: false` with no explanation. That is worse than a missing feature: a button
that does nothing and explains nothing sends someone hunting a fault that is not there.

  TC-SIM-01  the simulator genuinely is absent (so the rest of this file is about reality)
  TC-SIM-02  a start attempt records WHY, rather than only failing to run
  TC-SIM-03  the status endpoint reports availability and the reason
  TC-SIM-04  the start endpoint reports the reason too
  TC-SIM-05  a real simulator would still start — the check is absence, not a hard disable
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from app.services.simulator_manager import (
    NOT_INSTALLED_MESSAGE,
    SIMULATOR_PATH,
    SimulatorManager,
    simulator_available,
)


def test_tc_sim_01_the_simulator_is_actually_absent():
    """Stated as a test so this file is never read as hypothetical.

    If someone restores a simulator, this fails and the whole file should be revisited —
    which is the correct prompt, not a nuisance.
    """
    assert not SIMULATOR_PATH.is_file(), (
        f"{SIMULATOR_PATH} now exists. The simulator has been restored, so revisit this file "
        f"and the not-installed reporting it covers."
    )
    assert simulator_available() is False


def test_tc_sim_02_start_records_why_it_could_not():
    """The manager remembers the reason instead of leaving callers with 'not running'."""
    mgr = SimulatorManager()
    assert mgr.last_error is None

    mgr.start(pedestal_ids=[1])

    assert mgr.is_running is False
    assert mgr.last_error == NOT_INSTALLED_MESSAGE
    assert "be0df4f" in mgr.last_error, \
        "the message should name the commit, so the next reader can find what happened"
    assert "not installed" in mgr.last_error.lower()


def test_tc_sim_03_status_endpoint_reports_availability_and_reason(client, auth_headers):
    """`running: false` alone is what hid this for six months."""
    r = client.post("/api/pedestals/", json={
        "name": "Sim Absence Pedestal", "location": "Sim Dock", "data_mode": "synthetic",
    }, headers=auth_headers)
    pid = r.json()["id"]

    body = client.get(f"/api/pedestals/{pid}/simulator/status").json()
    assert body["available"] is False, \
        "the endpoint must say the simulator cannot run, not merely that it is not running"
    assert body["running"] is False


def test_tc_sim_04_start_endpoint_reports_the_reason(client, auth_headers):
    """An operator pressing the button gets an explanation in the response."""
    r = client.post("/api/pedestals/", json={
        "name": "Sim Start Pedestal", "location": "Sim Dock 2", "data_mode": "real",
    }, headers=auth_headers)
    pid = r.json()["id"]

    started = client.post(f"/api/pedestals/{pid}/simulator/start", headers=auth_headers)
    assert started.status_code == 200, started.text
    body = started.json()
    assert body["running"] is False
    assert body["reason"], (
        "the start endpoint returned running:false with no reason — exactly the behaviour "
        "that made this invisible"
    )
    assert "not installed" in body["reason"].lower()


def test_tc_sim_05_a_present_simulator_would_still_start(tmp_path):
    """The guard is about ABSENCE, not a disable switch.

    Without this, someone restoring the simulator could reasonably fear the check now blocks
    it. It does not: `simulator_available()` is a file test, and a real file proceeds to Popen.
    """
    fake = tmp_path / "pedestal_simulator.py"
    fake.write_text("import time\nwhile True: time.sleep(1)\n")

    mgr = SimulatorManager()
    with patch("app.services.simulator_manager.SIMULATOR_PATH", fake), \
         patch("app.services.simulator_manager.subprocess.Popen") as popen:
        popen.return_value.poll.return_value = None
        mgr.start(pedestal_ids=[1, 2])

    assert popen.called, "a simulator that exists must still be started"
    assert mgr.last_error is None, "a successful start must clear the previous reason"
    args = popen.call_args[0][0]
    assert str(fake) in args
    assert "--pedestal-ids" in args and "1,2" in args
