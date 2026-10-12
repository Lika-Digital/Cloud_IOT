"""energy_intervals.berth_id — decision 9, block 2, 2026-10-12.

MEASURED (docs/ui_v2_spec.md §6): `berth_ref` is ONE free-text label per PEDESTAL, copied onto
every interval row, so all four berths of a cabinet carried the same value — an interval has
never been attributable to a berth. The stable identifier is `berths.id`, mapped per socket by
`berth_assignments`.

  TC-EIB-01  a row for a socket assigned to a berth carries that berth's id
  TC-EIB-02  a row for an unassigned socket carries NULL — "not known", never 0, never a guess
  TC-EIB-03  the migration adds the column to an existing database and leaves every old row NULL
  TC-EIB-04  berth_ref is still written exactly as before (no invoice is ever re-keyed)

TC-EIB-01/03 FAIL on the code before this change (shown 2026-10-12).
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine

from conftest import TestSession as _S

PID = 9300
BERTH = 4242


@pytest.fixture(autouse=True)
def _isolate():
    from app.models.pedestal import Pedestal
    from app.models.energy_interval import EnergyInterval
    from app.models.session import Session as SModel
    from app.models.berth_assignment import BerthAssignment
    from app.models.pedestal_config import PedestalConfig
    db = _S()
    try:
        if db.get(Pedestal, PID) is None:
            db.add(Pedestal(id=PID, name="Berth-id Pedestal", location="Dock B", data_mode="synthetic"))
        for m in (EnergyInterval, SModel, BerthAssignment, PedestalConfig):
            db.query(m).filter(m.pedestal_id == PID).delete(synchronize_session=False)
        db.add(PedestalConfig(pedestal_id=PID, berth_ref="PIER-B LABEL"))
        db.add(BerthAssignment(berth_id=BERTH, pedestal_id=PID, socket_id=2,
                               assigned_by="test@test.local"))
        db.commit()
    finally:
        db.close()
    yield


def _flush(socket_id: int):
    from app.models.session import Session as SModel
    from app.models.socket_config import SocketConfig
    from app.services import energy_interval_service as eis
    db = _S()
    try:
        cfg = db.query(SocketConfig).filter(SocketConfig.pedestal_id == PID,
                                            SocketConfig.socket_id == socket_id).first()
        if cfg is None:
            cfg = SocketConfig(pedestal_id=PID, socket_id=socket_id)
            db.add(cfg)
        cfg.meter_energy_kwh = 501.0
        s = SModel(pedestal_id=PID, socket_id=socket_id, type="electricity", status="active",
                   started_at=datetime.utcnow() - timedelta(hours=1), energy_kwh=1.0,
                   energy_logged_kwh=0.0, meter_energy_start_kwh=500.0)
        db.add(s)
        db.commit()
        row = eis.flush_session_interval(db, s, now=datetime.utcnow())
        db.commit()
        assert row is not None, "the flush wrote no row — the test proves nothing"
        return row.berth_id, row.berth_ref
    finally:
        db.close()


def test_tc_eib_01_assigned_socket_carries_the_berth_id():
    berth_id, _ = _flush(socket_id=2)
    assert berth_id == BERTH


def test_tc_eib_02_unassigned_socket_is_null_not_zero():
    berth_id, _ = _flush(socket_id=3)
    assert berth_id is None


def test_tc_eib_04_berth_ref_unchanged():
    _, berth_ref = _flush(socket_id=2)
    assert berth_ref == "PIER-B LABEL"


def test_tc_eib_03_migration_adds_the_column_and_old_rows_stay_null(tmp_path):
    """An existing cabinet database: energy_intervals WITHOUT berth_id, with rows in it."""
    from app import database
    path = tmp_path / "old_pedestal.db"
    eng = create_engine(f"sqlite:///{path.as_posix()}")
    database.import_all_models()
    database.Base.metadata.create_all(bind=eng)
    eng.dispose()

    con = sqlite3.connect(path)
    cols = [r[1] for r in con.execute("PRAGMA table_info(energy_intervals)")]
    if "berth_id" in cols:
        con.execute("ALTER TABLE energy_intervals DROP COLUMN berth_id")
    for i in range(3):
        con.execute("INSERT INTO energy_intervals (pedestal_id, socket_id, origin, berth_ref, created_at, "
                    "interval_start, interval_end, kwh) VALUES (1, 1, 'operator', 'OLD', "
                    "'2026-10-01 10:15:00', '2026-10-01 10:00:00', '2026-10-01 10:15:00', 0.5)")
    con.commit()
    con.close()

    eng = create_engine(f"sqlite:///{path.as_posix()}")
    try:
        with patch.object(database, "engine", eng):
            database._migrate_schema()
    finally:
        eng.dispose()

    con = sqlite3.connect(path)
    try:
        cols = [r[1] for r in con.execute("PRAGMA table_info(energy_intervals)")]
        assert "berth_id" in cols, "the migration did not add energy_intervals.berth_id"
        rows = con.execute("SELECT berth_id, berth_ref FROM energy_intervals").fetchall()
        assert rows == [(None, "OLD")] * 3, f"old rows changed: {rows}"
    finally:
        con.close()
