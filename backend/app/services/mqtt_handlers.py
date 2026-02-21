import json
import logging
import re
from datetime import datetime

from ..database import SessionLocal
from ..services.session_service import session_service
from ..services.websocket_manager import ws_manager

logger = logging.getLogger(__name__)

# Topic patterns
SOCKET_STATUS_RE = re.compile(r"pedestal/(\d+)/socket/(\d+)/status")
SOCKET_POWER_RE = re.compile(r"pedestal/(\d+)/socket/(\d+)/power")
WATER_FLOW_RE = re.compile(r"pedestal/(\d+)/water/flow")
HEARTBEAT_RE = re.compile(r"pedestal/(\d+)/heartbeat")
SENSOR_TEMP_RE = re.compile(r"pedestal/(\d+)/sensors/temperature")
SENSOR_MOIST_RE = re.compile(r"pedestal/(\d+)/sensors/moisture")
DIAGNOSTICS_RE  = re.compile(r"pedestal/(\d+)/diagnostics/response")


async def handle_message(topic: str, payload: str):
    try:
        if m := SOCKET_STATUS_RE.match(topic):
            await _handle_socket_status(int(m.group(1)), int(m.group(2)), payload)
        elif m := SOCKET_POWER_RE.match(topic):
            await _handle_socket_power(int(m.group(1)), int(m.group(2)), payload)
        elif m := WATER_FLOW_RE.match(topic):
            await _handle_water_flow(int(m.group(1)), payload)
        elif m := HEARTBEAT_RE.match(topic):
            await _handle_heartbeat(int(m.group(1)), payload)
        elif m := SENSOR_TEMP_RE.match(topic):
            await _handle_temperature(int(m.group(1)), payload)
        elif m := SENSOR_MOIST_RE.match(topic):
            await _handle_moisture(int(m.group(1)), payload)
        elif m := DIAGNOSTICS_RE.match(topic):
            await _handle_diagnostics(int(m.group(1)), payload)
    except Exception as e:
        logger.error(f"Error handling MQTT message on {topic}: {e}")


async def _handle_socket_status(pedestal_id: int, socket_id: int, payload: str):
    status = payload.strip().strip('"')
    db = SessionLocal()
    try:
        if status == "connected":
            existing = session_service.get_active_for_socket(db, pedestal_id, socket_id)
            if not existing:
                session = session_service.create_pending(db, pedestal_id, socket_id, "electricity")
                await ws_manager.broadcast({
                    "event": "session_created",
                    "data": {
                        "session_id": session.id,
                        "pedestal_id": pedestal_id,
                        "socket_id": socket_id,
                        "type": "electricity",
                        "status": "pending",
                        "started_at": session.started_at.isoformat(),
                    },
                })
        elif status == "disconnected":
            session = session_service.get_active_for_socket(db, pedestal_id, socket_id)
            if session and session.status == "active":
                session_service.complete(db, session)
                await ws_manager.broadcast({
                    "event": "session_completed",
                    "data": {
                        "session_id": session.id,
                        "pedestal_id": pedestal_id,
                        "socket_id": socket_id,
                        "energy_kwh": session.energy_kwh,
                    },
                })
    finally:
        db.close()


async def _handle_socket_power(pedestal_id: int, socket_id: int, payload: str):
    try:
        data = json.loads(payload)
        watts = float(data["watts"])
        kwh_total = float(data["kwh_total"])
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logger.warning(f"Invalid power payload: {payload} — {e}")
        return

    db = SessionLocal()
    try:
        session = session_service.get_active_for_socket(db, pedestal_id, socket_id)
        session_id = session.id if session and session.status == "active" else None

        session_service.add_reading(db, session_id, pedestal_id, socket_id, "power_watts", watts, "W")
        session_service.add_reading(db, session_id, pedestal_id, socket_id, "kwh_total", kwh_total, "kWh")

        await ws_manager.broadcast({
            "event": "power_reading",
            "data": {
                "pedestal_id": pedestal_id,
                "socket_id": socket_id,
                "session_id": session_id,
                "watts": watts,
                "kwh_total": kwh_total,
                "timestamp": datetime.utcnow().isoformat(),
            },
        })
    finally:
        db.close()


async def _handle_water_flow(pedestal_id: int, payload: str):
    try:
        data = json.loads(payload)
        lpm = float(data["lpm"])
        total_liters = float(data["total_liters"])
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logger.warning(f"Invalid water payload: {payload} — {e}")
        return

    db = SessionLocal()
    try:
        session = session_service.get_active_for_socket(db, pedestal_id, None)
        session_id = session.id if session and session.status == "active" else None

        if session_id is None:
            # Auto-create water session on first flow
            if lpm > 0:
                session = session_service.create_pending(db, pedestal_id, None, "water")
                session_id = session.id
                await ws_manager.broadcast({
                    "event": "session_created",
                    "data": {
                        "session_id": session.id,
                        "pedestal_id": pedestal_id,
                        "socket_id": None,
                        "type": "water",
                        "status": "pending",
                        "started_at": session.started_at.isoformat(),
                    },
                })

        session_service.add_reading(db, session_id, pedestal_id, None, "water_lpm", lpm, "L/min")
        session_service.add_reading(db, session_id, pedestal_id, None, "total_liters", total_liters, "L")

        await ws_manager.broadcast({
            "event": "water_reading",
            "data": {
                "pedestal_id": pedestal_id,
                "session_id": session_id,
                "lpm": lpm,
                "total_liters": total_liters,
                "timestamp": datetime.utcnow().isoformat(),
            },
        })
    finally:
        db.close()


async def _handle_heartbeat(pedestal_id: int, payload: str):
    try:
        data = json.loads(payload)
        await ws_manager.broadcast({
            "event": "heartbeat",
            "data": {
                "pedestal_id": pedestal_id,
                "online": data.get("online", True),
                "timestamp": data.get("timestamp", datetime.utcnow().isoformat()),
            },
        })
    except Exception as e:
        logger.warning(f"Invalid heartbeat payload: {e}")


async def _handle_temperature(pedestal_id: int, payload: str):
    try:
        data = json.loads(payload)
        value = float(data["value"])
        alarm = value > 50.0
        db = SessionLocal()
        try:
            session_service.add_reading(db, None, pedestal_id, None, "temperature", value, "°C")
        finally:
            db.close()
        await ws_manager.broadcast({
            "event": "temperature_reading",
            "data": {
                "pedestal_id": pedestal_id,
                "value": round(value, 1),
                "alarm": alarm,
                "timestamp": datetime.utcnow().isoformat(),
            },
        })
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logger.warning(f"Invalid temperature payload: {payload} — {e}")


async def _handle_moisture(pedestal_id: int, payload: str):
    try:
        data = json.loads(payload)
        value = float(data["value"])
        alarm = value > 90.0
        db = SessionLocal()
        try:
            session_service.add_reading(db, None, pedestal_id, None, "moisture", value, "%")
        finally:
            db.close()
        await ws_manager.broadcast({
            "event": "moisture_reading",
            "data": {
                "pedestal_id": pedestal_id,
                "value": round(value, 1),
                "alarm": alarm,
                "timestamp": datetime.utcnow().isoformat(),
            },
        })
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logger.warning(f"Invalid moisture payload: {payload} — {e}")


async def _handle_diagnostics(pedestal_id: int, payload: str):
    """Receive diagnostics response from pedestal and resolve the waiting API call."""
    try:
        from ..services.diagnostics_manager import diagnostics_manager
        data = json.loads(payload)
        diagnostics_manager.complete_request(pedestal_id, data)
        await ws_manager.broadcast({
            "event": "diagnostics_result",
            "data": {"pedestal_id": pedestal_id, "results": data},
        })
    except (json.JSONDecodeError, Exception) as e:
        logger.warning(f"Invalid diagnostics response: {payload} — {e}")
