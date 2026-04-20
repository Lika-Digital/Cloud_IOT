from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session as DBSession
from sqlalchemy import func
from ..database import get_db
from ..models.session import Session
from ..models.sensor_reading import SensorReading
from datetime import datetime, timedelta

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/consumption/daily")
def daily_consumption(
    pedestal_id: int | None = None,
    days: int = Query(default=30, le=365),
    db: DBSession = Depends(get_db),
):
    since = datetime.utcnow() - timedelta(days=days)
    q = (
        db.query(
            func.date(Session.started_at).label("date"),
            func.sum(Session.energy_kwh).label("energy_kwh"),
            func.sum(Session.water_liters).label("water_liters"),
            func.count(Session.id).label("session_count"),
        )
        .filter(Session.status == "completed", Session.started_at >= since)
    )
    if pedestal_id:
        q = q.filter(Session.pedestal_id == pedestal_id)
    rows = q.group_by(func.date(Session.started_at)).order_by("date").all()

    return [
        {
            "date": row.date,
            "energy_kwh": row.energy_kwh or 0.0,
            "water_liters": row.water_liters or 0.0,
            "session_count": row.session_count,
        }
        for row in rows
    ]


@router.get("/consumption/by-socket")
def consumption_by_socket(
    pedestal_id: int | None = None,
    db: DBSession = Depends(get_db),
):
    q = (
        db.query(
            Session.socket_id,
            Session.type,
            func.sum(Session.energy_kwh).label("total_energy_kwh"),
            func.sum(Session.water_liters).label("total_water_liters"),
            func.count(Session.id).label("session_count"),
        )
        .filter(Session.status == "completed")
    )
    if pedestal_id:
        q = q.filter(Session.pedestal_id == pedestal_id)
    rows = q.group_by(Session.socket_id, Session.type).all()

    return [
        {
            "socket_id": row.socket_id,
            "type": row.type,
            "total_energy_kwh": row.total_energy_kwh or 0.0,
            "total_water_liters": row.total_water_liters or 0.0,
            "session_count": row.session_count,
        }
        for row in rows
    ]


@router.get("/sessions/summary")
def session_summary(pedestal_id: int | None = None, db: DBSession = Depends(get_db)):
    q = db.query(Session)
    if pedestal_id:
        q = q.filter(Session.pedestal_id == pedestal_id)

    all_sessions = q.all()
    total = len(all_sessions)
    by_status = {}
    for s in all_sessions:
        by_status[s.status] = by_status.get(s.status, 0) + 1

    completed = [s for s in all_sessions if s.status == "completed"]
    total_kwh = sum(s.energy_kwh or 0 for s in completed)
    total_liters = sum(s.water_liters or 0 for s in completed)

    return {
        "total_sessions": total,
        "by_status": by_status,
        "total_energy_kwh": round(total_kwh, 3),
        "total_water_liters": round(total_liters, 2),
        "completed_sessions": len(completed),
    }


@router.get("/consumption/by-pedestal")
def consumption_by_pedestal(db: DBSession = Depends(get_db)):
    """Cross-pedestal comparison — total energy, water and sessions per pedestal."""
    rows = (
        db.query(
            Session.pedestal_id,
            func.sum(Session.energy_kwh).label("total_energy_kwh"),
            func.sum(Session.water_liters).label("total_water_liters"),
            func.count(Session.id).label("session_count"),
        )
        .filter(Session.status == "completed")
        .group_by(Session.pedestal_id)
        .order_by(Session.pedestal_id)
        .all()
    )
    return [
        {
            "pedestal_id": row.pedestal_id,
            "total_energy_kwh": round(row.total_energy_kwh or 0.0, 3),
            "total_water_liters": round(row.total_water_liters or 0.0, 2),
            "session_count": row.session_count,
        }
        for row in rows
    ]


@router.get("/readings/recent")
def recent_readings(
    pedestal_id: int | None = None,
    socket_id: int | None = None,
    reading_type: str | None = None,
    limit: int = Query(default=50, le=500),
    db: DBSession = Depends(get_db),
):
    q = db.query(SensorReading)
    if pedestal_id:
        q = q.filter(SensorReading.pedestal_id == pedestal_id)
    if socket_id is not None:
        q = q.filter(SensorReading.socket_id == socket_id)
    if reading_type:
        q = q.filter(SensorReading.type == reading_type)
    readings = q.order_by(SensorReading.timestamp.desc()).limit(limit).all()

    return [
        {
            "id": r.id,
            "session_id": r.session_id,
            "pedestal_id": r.pedestal_id,
            "socket_id": r.socket_id,
            "type": r.type,
            "value": r.value,
            "unit": r.unit,
            "timestamp": r.timestamp.isoformat(),
        }
        for r in readings
    ]
