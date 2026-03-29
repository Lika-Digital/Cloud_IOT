import json
import logging
import re
from datetime import datetime

from ..database import SessionLocal
from ..services.session_service import session_service
from ..services.websocket_manager import ws_manager

logger = logging.getLogger(__name__)

# Tracks most-recent heartbeat per pedestal — read by _comm_loss_watchdog in main.py
last_heartbeat: dict[int, datetime] = {}

# Topic patterns
SOCKET_STATUS_RE  = re.compile(r"pedestal/(\d+)/socket/(\d+)/status")
SOCKET_POWER_RE   = re.compile(r"pedestal/(\d+)/socket/(\d+)/power")
WATER_FLOW_RE     = re.compile(r"pedestal/(\d+)/water/flow")
HEARTBEAT_RE      = re.compile(r"pedestal/(\d+)/heartbeat")
SENSOR_TEMP_RE    = re.compile(r"pedestal/(\d+)/sensors/temperature")
SENSOR_MOIST_RE   = re.compile(r"pedestal/(\d+)/sensors/moisture")
DIAGNOSTICS_RE    = re.compile(r"pedestal/(\d+)/diagnostics/response")
SENSOR_REGISTER_RE = re.compile(r"pedestal/(\d+)/register")


def _hw_warn(source: str, message: str, details: str | None = None):
    try:
        from .error_log_service import log_warning
        log_warning("hw", source, message, details=details)
    except Exception:
        pass


def _hw_error(source: str, message: str, details: str | None = None):
    try:
        from .error_log_service import log_error
        log_error("hw", source, message, details=details)
    except Exception:
        pass


def _ensure_pedestal(db, pedestal_id: int):
    """
    Auto-create a Pedestal row the first time any MQTT message arrives for it.
    Called inside an open DB session — caller must commit.
    """
    from ..models.pedestal import Pedestal
    if not db.get(Pedestal, pedestal_id):
        db.add(Pedestal(
            id=pedestal_id,
            name=f"Pedestal {pedestal_id}",
            location="",
            data_mode="real",
            initialized=False,
            mobile_enabled=False,
        ))
        db.commit()
        logger.info("Auto-created Pedestal %d from first MQTT message", pedestal_id)


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
        elif m := SENSOR_REGISTER_RE.match(topic):
            await _handle_auto_register(int(m.group(1)), payload)
    except Exception as e:
        logger.error(f"Error handling MQTT message on {topic}: {e}")
        _hw_error("mqtt_handlers", f"Unhandled error on topic {topic}: {e}")


async def _handle_socket_status(pedestal_id: int, socket_id: int, payload: str):
    status = payload.strip().strip('"')
    db = SessionLocal()
    try:
        # Persist physical connection state so the session API can validate it
        if status in ("connected", "disconnected"):
            from ..models.pedestal_config import SocketState
            _ensure_pedestal(db, pedestal_id)
            state = db.query(SocketState).filter(
                SocketState.pedestal_id == pedestal_id,
                SocketState.socket_id == socket_id,
            ).first()
            if state:
                state.connected = (status == "connected")
                state.updated_at = datetime.utcnow()
            else:
                db.add(SocketState(
                    pedestal_id=pedestal_id,
                    socket_id=socket_id,
                    connected=(status == "connected"),
                ))
            db.commit()

        if status == "disconnected":
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
                        "customer_id": session.customer_id,
                    },
                })
                if session.customer_id:
                    from ..auth.user_database import UserSessionLocal
                    from ..services.invoice_service import create_invoice_for_session
                    user_db = UserSessionLocal()
                    try:
                        await create_invoice_for_session(db, user_db, session)
                    except Exception as e:
                        _hw_error(
                            f"pedestal_{pedestal_id}",
                            f"Invoice creation failed for session {session.id} on disconnect: {e}",
                        )
                    finally:
                        user_db.close()
        elif status not in ("connected", "disconnected"):
            _hw_warn(
                f"pedestal_{pedestal_id}",
                f"Unknown socket status '{status}' on socket {socket_id}",
            )
    finally:
        db.close()


async def _handle_socket_power(pedestal_id: int, socket_id: int, payload: str):
    try:
        data = json.loads(payload)
        watts = float(data["watts"])
        kwh_total = float(data["kwh_total"])
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logger.warning(f"Invalid power payload: {payload} — {e}")
        _hw_warn(
            f"pedestal_{pedestal_id}",
            f"Invalid power payload on socket {socket_id}: {e}",
            details=payload[:200],
        )
        return

    db = SessionLocal()
    try:
        session = session_service.get_active_for_socket(db, pedestal_id, socket_id)
        session_id = session.id if session and session.status == "active" else None
        customer_id = session.customer_id if session else None

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
                "customer_id": customer_id,
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
        _hw_warn(
            f"pedestal_{pedestal_id}",
            f"Invalid water flow payload: {e}",
            details=payload[:200],
        )
        return

    db = SessionLocal()
    try:
        session = session_service.get_active_for_socket(db, pedestal_id, None)
        session_id = session.id if session and session.status == "active" else None
        customer_id = session.customer_id if session else None

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
                "customer_id": customer_id,
            },
        })
    finally:
        db.close()


async def _handle_heartbeat(pedestal_id: int, payload: str):
    try:
        data = json.loads(payload)
        now = datetime.utcnow()
        last_heartbeat[pedestal_id] = now  # update for comm-loss watchdog

        # Persist heartbeat timestamp + mark OPTA connected in DB
        try:
            from ..models.pedestal_config import PedestalConfig
            db = SessionLocal()
            try:
                _ensure_pedestal(db, pedestal_id)
                cfg = db.query(PedestalConfig).filter(
                    PedestalConfig.pedestal_id == pedestal_id
                ).first()
                if cfg is None:
                    cfg = PedestalConfig(
                        pedestal_id=pedestal_id,
                        opta_connected=1,
                        last_heartbeat=now,
                        updated_at=now,
                    )
                    db.add(cfg)
                else:
                    cfg.opta_connected = 1
                    cfg.last_heartbeat = now
                    cfg.updated_at = now
                db.commit()
            finally:
                db.close()
        except Exception as db_err:
            logger.warning(f"Heartbeat DB update failed for pedestal {pedestal_id}: {db_err}")

        await ws_manager.broadcast({
            "event": "heartbeat",
            "data": {
                "pedestal_id": pedestal_id,
                "online": data.get("online", True),
                "timestamp": data.get("timestamp", now.isoformat()),
            },
        })
        await ws_manager.broadcast({
            "event": "pedestal_health_updated",
            "data": {
                "pedestal_id": pedestal_id,
                "opta_connected": True,
                "last_heartbeat": now.isoformat(),
            },
        })
    except Exception as e:
        logger.warning(f"Invalid heartbeat payload: {e}")
        _hw_warn(f"pedestal_{pedestal_id}", f"Invalid heartbeat payload: {e}", details=payload[:200])


async def _handle_auto_register(pedestal_id: int, payload: str):
    """Auto-upsert sensor into pedestal_sensors when device publishes pedestal/{id}/register."""
    try:
        data = json.loads(payload)
        sensor_name = data.get("sensor_name", "").strip()
        sensor_type = data.get("sensor_type", "").strip()
        mqtt_topic  = data.get("mqtt_topic", "").strip()
        unit        = data.get("unit", "")

        if not sensor_name or not mqtt_topic:
            logger.warning(f"Auto-register: missing sensor_name or mqtt_topic from pedestal {pedestal_id}")
            return

        from ..models.pedestal_config import PedestalSensor
        db = SessionLocal()
        try:
            _ensure_pedestal(db, pedestal_id)
            existing = db.query(PedestalSensor).filter(
                PedestalSensor.pedestal_id == pedestal_id,
                PedestalSensor.mqtt_topic == mqtt_topic,
            ).first()
            if existing:
                existing.sensor_name = sensor_name
                existing.sensor_type = sensor_type
                existing.unit = unit
                existing.source = "auto_mqtt"
            else:
                db.add(PedestalSensor(
                    pedestal_id=pedestal_id,
                    sensor_name=sensor_name,
                    sensor_type=sensor_type,
                    mqtt_topic=mqtt_topic,
                    unit=unit,
                    source="auto_mqtt",
                    created_at=datetime.utcnow(),
                ))
            db.commit()
            logger.info(f"Auto-registered sensor '{sensor_name}' for pedestal {pedestal_id}")
        finally:
            db.close()
    except (json.JSONDecodeError, Exception) as e:
        logger.warning(f"Auto-register parse error on pedestal {pedestal_id}: {e}")


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

        if alarm:
            _hw_warn(
                f"pedestal_{pedestal_id}",
                f"Temperature ALARM: {round(value, 1)}°C (threshold 50°C)",
            )
            try:
                from .alarm_service import trigger_alarm
                trigger_alarm(
                    alarm_type="temperature",
                    source="sensor_auto",
                    message=f"Pedestal {pedestal_id}: temperature {round(value, 1)}°C exceeds 50°C threshold",
                    pedestal_id=pedestal_id,
                    deduplicate=True,
                )
            except Exception:
                pass

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
        _hw_warn(f"pedestal_{pedestal_id}", f"Invalid temperature payload: {e}", details=payload[:200])


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

        if alarm:
            _hw_warn(
                f"pedestal_{pedestal_id}",
                f"Moisture ALARM: {round(value, 1)}% (threshold 90%)",
            )
            try:
                from .alarm_service import trigger_alarm
                trigger_alarm(
                    alarm_type="moisture",
                    source="sensor_auto",
                    message=f"Pedestal {pedestal_id}: moisture {round(value, 1)}% exceeds 90% threshold",
                    pedestal_id=pedestal_id,
                    deduplicate=True,
                )
            except Exception:
                pass

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
        _hw_warn(f"pedestal_{pedestal_id}", f"Invalid moisture payload: {e}", details=payload[:200])


async def _handle_diagnostics(pedestal_id: int, payload: str):
    try:
        from ..services.diagnostics_manager import diagnostics_manager
        data = json.loads(payload)
        diagnostics_manager.complete_request(pedestal_id, data)

        # Log any failed sensors as HW errors and raise operational alarm
        failed = [k for k, v in data.items() if v != "ok"]
        if failed:
            _hw_error(
                f"pedestal_{pedestal_id}",
                f"Diagnostics: {len(failed)} sensor(s) failed — {', '.join(failed)}",
                details=json.dumps(data),
            )
            try:
                from .alarm_service import trigger_alarm
                trigger_alarm(
                    alarm_type="operational_failure",
                    source="sensor_auto",
                    message=f"Pedestal {pedestal_id}: diagnostics failure — {', '.join(failed)}",
                    pedestal_id=pedestal_id,
                    details=json.dumps(data),
                    deduplicate=True,
                )
            except Exception:
                pass

        await ws_manager.broadcast({
            "event": "diagnostics_result",
            "data": {"pedestal_id": pedestal_id, "results": data},
        })
    except (json.JSONDecodeError, Exception) as e:
        logger.warning(f"Invalid diagnostics response: {payload} — {e}")
        _hw_error(f"pedestal_{pedestal_id}", f"Diagnostics response parse error: {e}", details=payload[:200])
