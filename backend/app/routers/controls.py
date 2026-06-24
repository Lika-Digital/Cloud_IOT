from typing import Optional
import asyncio
import json
import logging
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession
from ..database import get_db
from ..auth.user_database import get_user_db
from ..auth.customer_models import Customer
from ..models.session import Session
from ..models.pedestal_config import SocketState
from ..schemas.session import SessionResponse
from ..services.session_service import session_service
from ..services.mqtt_client import mqtt_service
from ..services.websocket_manager import ws_manager
from ..services.invoice_service import create_invoice_for_session
from ..services.audit_service import log_transition
from ..auth.dependencies import require_control, require_any_role
from ..auth.models import User
from ..time_utils import now_iso, iso_z

logger = logging.getLogger(__name__)


def _get_cabinet_id(db: DBSession, pedestal_id: int) -> str | None:
    """Return marina cabinet string ID if this pedestal is a marina cabinet, else None."""
    from ..models.pedestal_config import PedestalConfig
    cfg = db.query(PedestalConfig).filter(PedestalConfig.pedestal_id == pedestal_id).first()
    return getattr(cfg, "opta_client_id", None) if cfg else None


async def _operator_disable_auto_activate(db: DBSession, pedestal_id: int, socket_id: int) -> None:
    """B6 (v3.28) — on an OPERATOR stop, disable auto-activate for this electricity
    socket so a still-plugged cable doesn't immediately re-activate it (stop/auto
    loop). Broadcasts `socket_auto_activate_changed` so the dashboard toggle flips
    OFF live. No-op if already off (idempotent). Called ONLY from the operator
    stop endpoints — NOT from the shared _publish_session_control, so ERP stop and
    the meter overload autostop never disable auto-activate."""
    from ..models.socket_config import SocketConfig
    cfg = db.query(SocketConfig).filter(
        SocketConfig.pedestal_id == pedestal_id,
        SocketConfig.socket_id == socket_id,
    ).first()
    if cfg is None or not cfg.auto_activate:
        return
    cfg.auto_activate = False
    db.commit()
    await ws_manager.broadcast({
        "event": "socket_auto_activate_changed",
        "data": {"pedestal_id": pedestal_id, "socket_id": socket_id, "auto_activate": False},
    })


def _publish_socket_approve(db: DBSession, pedestal_id: int, socket_id: int):
    """Approve socket — Opta valid actions: activate, stop only."""
    cabinet_id = _get_cabinet_id(db, pedestal_id)
    msg_id = str(int(datetime.utcnow().timestamp() * 1000))
    if cabinet_id:
        mqtt_service.publish(
            f"marina/cabinet/{cabinet_id}/cmd/socket/E{socket_id}",
            json.dumps({"cmd": "enable"}),
        )
        # Opta expects {"action": "activate"}, not {"cmd": "enable"}
        mqtt_service.publish(
            f"opta/cmd/socket/Q{socket_id}",
            json.dumps({"msgId": msg_id, "cabinetId": cabinet_id, "action": "activate"}),
        )
    else:
        mqtt_service.publish(
            f"pedestal/{pedestal_id}/socket/{socket_id}/command",
            json.dumps({"cmd": "approved"}),
        )


def _publish_socket_reject(db: DBSession, pedestal_id: int, socket_id: int, reason: str):
    """Reject socket — Opta valid actions: activate, stop only."""
    cabinet_id = _get_cabinet_id(db, pedestal_id)
    msg_id = str(int(datetime.utcnow().timestamp() * 1000))
    if cabinet_id:
        mqtt_service.publish(
            f"marina/cabinet/{cabinet_id}/cmd/socket/E{socket_id}",
            json.dumps({"cmd": "disable"}),
        )
        # Opta expects {"action": "stop"}, not {"cmd": "disable"}
        mqtt_service.publish(
            f"opta/cmd/socket/Q{socket_id}",
            json.dumps({"msgId": msg_id, "cabinetId": cabinet_id, "action": "stop"}),
        )
    else:
        mqtt_service.publish(
            f"pedestal/{pedestal_id}/socket/{socket_id}/command",
            json.dumps({"cmd": "rejected", "reason": reason}),
        )


def _publish_session_control(db: DBSession, session: Session, action: str):
    """Publish allow/deny/stop command, routing to marina and opta topics (or legacy).

    Opta valid actions: activate, stop (no maintenance, no enable/disable).
    """
    cabinet_id = _get_cabinet_id(db, session.pedestal_id)
    if cabinet_id:
        msg_id = str(int(datetime.utcnow().timestamp() * 1000))
        if session.type == "electricity":
            sid = session.socket_id or 1
            if action == "allow":
                mqtt_service.publish(
                    f"marina/cabinet/{cabinet_id}/cmd/socket/E{sid}",
                    json.dumps({"cmd": "enable"}),
                )
                # Opta expects {"action": "activate"}, not {"cmd": "enable"}
                mqtt_service.publish(
                    f"opta/cmd/socket/Q{sid}",
                    json.dumps({"msgId": msg_id, "cabinetId": cabinet_id, "action": "activate"}),
                )
            elif action == "deny":
                mqtt_service.publish(
                    f"marina/cabinet/{cabinet_id}/cmd/socket/E{sid}",
                    json.dumps({"cmd": "disable"}),
                )
                # Opta expects {"action": "stop"}, not {"cmd": "disable"}
                mqtt_service.publish(
                    f"opta/cmd/socket/Q{sid}",
                    json.dumps({"msgId": msg_id, "cabinetId": cabinet_id, "action": "stop"}),
                )
            elif action == "stop":
                mqtt_service.publish(
                    f"marina/cabinet/{cabinet_id}/outlet/PWR-{sid}/cmd/stop",
                    json.dumps({"cmd": "stop"}),
                )
                mqtt_service.publish(
                    f"opta/cmd/socket/Q{sid}",
                    json.dumps({"msgId": msg_id, "cabinetId": cabinet_id, "action": "stop"}),
                )
        elif session.type == "water":
            wid = session.socket_id or 1
            if action in ("deny", "stop"):
                mqtt_service.publish(
                    f"marina/cabinet/{cabinet_id}/outlet/WTR-{wid}/cmd/stop",
                    json.dumps({"cmd": "stop"}),
                )
                # Opta expects {"action": "stop"}
                mqtt_service.publish(
                    f"opta/cmd/water/V{wid}",
                    json.dumps({"msgId": msg_id, "cabinetId": cabinet_id, "action": "stop"}),
                )
                # v3.9 — record operator-initiated manual stop so the next
                # post-diagnostic auto-open respects the 10-minute cooldown.
                from ..services.mqtt_handlers import last_valve_manual_stop_at
                last_valve_manual_stop_at[(session.pedestal_id, wid)] = datetime.utcnow()
            elif action == "allow":
                mqtt_service.publish(
                    f"opta/cmd/water/V{wid}",
                    json.dumps({"msgId": msg_id, "cabinetId": cabinet_id, "action": "activate"}),
                )
    else:
        mqtt_service.publish(_control_topic(session), action)


async def _send_expo_push(push_token: str, title: str, body: str, data: dict):
    """Fire-and-forget Expo push notification. Never raises."""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(
                "https://exp.host/--/api/v2/push/send",
                json={"to": push_token, "title": title, "body": body, "data": data},
            )
    except Exception as e:
        logger.warning(f"Push notification failed: {e}")

router = APIRouter(prefix="/api/controls", tags=["controls"])


class DenyBody(BaseModel):
    reason: Optional[str] = Field(None, max_length=500)


def _get_session_or_404(session_id: int, db: DBSession) -> Session:
    s = db.get(Session, session_id)
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    return s


def _control_topic(session: Session) -> str:
    if session.type == "electricity":
        return f"pedestal/{session.pedestal_id}/socket/{session.socket_id}/control"
    return f"pedestal/{session.pedestal_id}/water/control"


@router.post("/{session_id}/allow", response_model=SessionResponse)
async def allow_session(
    session_id: int,
    db: DBSession = Depends(get_db),
    user_db: DBSession = Depends(get_user_db),
    _: User = Depends(require_control),
):
    session = _get_session_or_404(session_id, db)
    if session.status != "pending":
        raise HTTPException(status_code=400, detail=f"Session is {session.status}, expected pending")

    session_service.activate(db, session)
    _publish_session_control(db, session, "allow")

    await ws_manager.broadcast({
        "event": "session_updated",
        "data": {
            "session_id": session.id,
            "pedestal_id": session.pedestal_id,
            "socket_id": session.socket_id,
            "type": session.type,
            "status": "active",
            "customer_id": session.customer_id,
            "deny_reason": None,
        },
    })

    # Fire-and-forget push notification
    if session.customer_id:
        customer = user_db.get(Customer, session.customer_id)
        if customer and getattr(customer, "push_token", None):
            asyncio.create_task(_send_expo_push(
                customer.push_token,
                title="Session Approved",
                body=f"Your {session.type} session on Pedestal {session.pedestal_id} has been approved.",
                data={"session_id": session.id},
            ))

    return session


@router.post("/{session_id}/deny", response_model=SessionResponse)
async def deny_session(
    session_id: int,
    body: DenyBody = DenyBody(),
    db: DBSession = Depends(get_db),
    user_db: DBSession = Depends(get_user_db),
    _: User = Depends(require_control),
):
    session = _get_session_or_404(session_id, db)
    if session.status != "pending":
        raise HTTPException(status_code=400, detail=f"Session is {session.status}, expected pending")

    session_service.deny(db, session, reason=body.reason)
    _publish_session_control(db, session, "deny")

    await ws_manager.broadcast({
        "event": "session_updated",
        "data": {
            "session_id": session.id,
            "pedestal_id": session.pedestal_id,
            "socket_id": session.socket_id,
            "type": session.type,
            "status": "denied",
            "customer_id": session.customer_id,
            "deny_reason": session.deny_reason,
        },
    })

    # Fire-and-forget push notification
    if session.customer_id:
        customer = user_db.get(Customer, session.customer_id)
        if customer and getattr(customer, "push_token", None):
            reason_text = session.deny_reason or "No reason provided."
            asyncio.create_task(_send_expo_push(
                customer.push_token,
                title="Session Denied",
                body=f"Your {session.type} session was denied. Reason: {reason_text}",
                data={"session_id": session.id},
            ))

    return session


@router.post("/{session_id}/stop", response_model=SessionResponse)
async def stop_session(
    session_id: int,
    db: DBSession = Depends(get_db),
    user_db: DBSession = Depends(get_user_db),
    _: User = Depends(require_control),
):
    session = _get_session_or_404(session_id, db)
    if session.status != "active":
        raise HTTPException(status_code=400, detail=f"Session is {session.status}, expected active")

    # B6 (v3.28) — operator stop disables auto-activate for this electricity
    # socket (before publishing stop) so the still-plugged cable doesn't loop.
    if session.type == "electricity" and session.socket_id is not None:
        await _operator_disable_auto_activate(db, session.pedestal_id, session.socket_id)

    session_service.complete(db, session)
    _publish_session_control(db, session, "stop")

    await ws_manager.broadcast({
        "event": "session_completed",
        "data": {
            "session_id": session.id,
            "pedestal_id": session.pedestal_id,
            "socket_id": session.socket_id,
            "type": session.type,
            "status": "completed",
            "energy_kwh": session.energy_kwh,
            "water_liters": session.water_liters,
            "customer_id": session.customer_id,
            "stopped_by": "operator",
        },
    })

    # Push notification — inform customer session was stopped by operator
    if session.customer_id:
        customer = user_db.get(Customer, session.customer_id)
        if customer and getattr(customer, "push_token", None):
            asyncio.create_task(_send_expo_push(
                customer.push_token,
                title="Session Stopped by Operator",
                body=f"Your {session.type} session on Pedestal {session.pedestal_id} was manually stopped by the marina operator.",
                data={"session_id": session.id, "stopped_by": "operator"},
            ))

    # Invoice creation is best-effort — session is already completed; don't abort on failure
    try:
        await create_invoice_for_session(db, user_db, session)
    except Exception as e:
        try:
            from ..services.error_log_service import log_error
            log_error(
                "system", "controls",
                f"Invoice creation failed for session {session.id} (session still completed): {e}",
                exc=e,
            )
        except Exception:
            pass

    return session


# ── Socket-level operator approval (before any session exists) ────────────────

def _require_smart_mode(db: DBSession, pedestal_id: int) -> None:
    """v3.30 — block NUC control when the pedestal is in standalone (SmartMode
    OFF). The Opta owns control and ignores NUC commands, so the dashboard is
    read-only; the API mirrors that by refusing socket/valve control actions.
    Returns 409 so the UI (which also grays the buttons) and any API client get
    a consistent, explainable rejection."""
    from ..models.pedestal_config import PedestalConfig
    cfg = db.query(PedestalConfig).filter(
        PedestalConfig.pedestal_id == pedestal_id
    ).first()
    if cfg is None or not cfg.smart_mode:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Smart Mode is OFF — the cabinet is in standalone control. "
                   "Enable Smart Mode to control sockets and valves from the dashboard.",
        )


def _get_socket_state_or_400(db: DBSession, pedestal_id: int, socket_id: int) -> SocketState:
    state = db.query(SocketState).filter(
        SocketState.pedestal_id == pedestal_id,
        SocketState.socket_id == socket_id,
    ).first()
    if not state or state.operator_status not in ("pending", "awaiting_activation"):
        raise HTTPException(status_code=400, detail="Socket is not in pending approval state")
    return state


@router.post("/sockets/{pedestal_id}/{socket_id}/approve", response_model=SessionResponse)
async def approve_socket(
    pedestal_id: int,
    socket_id: int,
    db: DBSession = Depends(get_db),
    user_db: DBSession = Depends(get_user_db),
    current_user: User = Depends(require_control),
):
    """
    Operator approves a socket that is in pending state (MQTT connected event fired).
    Creates and activates a session, clears the pending flag, publishes MQTT approved command.
    """
    state = _get_socket_state_or_400(db, pedestal_id, socket_id)

    existing = session_service.get_active_for_socket(db, pedestal_id, socket_id)
    if existing and existing.status == "active":
        raise HTTPException(status_code=409, detail="Socket already has an active session")

    # v3.30 — an overload alarm no longer blocks re-activation. The NUC raises
    # the alarm (operator acknowledges it) but never withholds control; the
    # operator may activate at any time.

    session = session_service.create_pending(db, pedestal_id, socket_id, "electricity")
    session_service.activate(db, session)

    state.operator_status = None
    state.operator_status_at = None
    db.commit()
    db.refresh(session)

    _publish_socket_approve(db, pedestal_id, socket_id)
    log_transition(
        db, session.id, pedestal_id, socket_id,
        "operator_approved", "operator", actor_id=current_user.id,
    )

    await ws_manager.broadcast({
        "event": "session_created",
        "data": {
            "session_id": session.id,
            "pedestal_id": pedestal_id,
            "socket_id": socket_id,
            "type": "electricity",
            "status": "active",
            "started_at": iso_z(session.started_at),
            "customer_id": None,
            "customer_name": None,
        },
    })
    return session


class RejectSocketBody(BaseModel):
    reason: Optional[str] = Field(None, max_length=500)


@router.post("/sockets/{pedestal_id}/{socket_id}/reject")
async def reject_socket(
    pedestal_id: int,
    socket_id: int,
    body: RejectSocketBody = RejectSocketBody(),
    db: DBSession = Depends(get_db),
    user_db: DBSession = Depends(get_user_db),
    current_user: User = Depends(require_control),
):
    """
    Operator rejects a socket in pending state.
    Publishes MQTT rejection command, marks socket as rejected, notifies dashboard.
    """
    state = _get_socket_state_or_400(db, pedestal_id, socket_id)

    reason = body.reason or "Operator denied"
    state.operator_status = "rejected"
    state.operator_status_at = datetime.utcnow()
    db.commit()

    _publish_socket_reject(db, pedestal_id, socket_id, reason)
    log_transition(
        db, None, pedestal_id, socket_id,
        "operator_rejected", "operator", actor_id=current_user.id, reason=reason,
    )

    await ws_manager.broadcast({
        "event": "socket_rejected",
        "data": {"pedestal_id": pedestal_id, "socket_id": socket_id},
    })
    return {"status": "rejected", "pedestal_id": pedestal_id, "socket_id": socket_id}


# ── Pedestal reset (opta/cmd/reset) ──────────────────────────────────────────

@router.post("/pedestal/{pedestal_id}/reset")
async def reset_pedestal(
    pedestal_id: int,
    db: DBSession = Depends(get_db),
    _: User = Depends(require_control),
):
    """
    Send a reset command to the pedestal.
    Publishes to opta/cmd/reset (cabinetId in payload) and legacy pedestal topic.
    """
    cabinet_id = _get_cabinet_id(db, pedestal_id)
    if cabinet_id:
        mqtt_service.publish(
            "opta/cmd/reset",
            json.dumps({"cabinetId": cabinet_id, "cmd": "reset"}),
        )
    else:
        mqtt_service.publish(
            f"pedestal/{pedestal_id}/cmd/reset",
            json.dumps({"cmd": "reset"}),
        )
    log_transition(db, None, pedestal_id, None, "reset_sent", "operator")
    await ws_manager.broadcast({
        "event": "pedestal_reset_sent",
        "data": {"pedestal_id": pedestal_id, "cabinet_id": cabinet_id},
    })
    return {"status": "reset_sent", "pedestal_id": pedestal_id}


# ── LED control (opta/cmd/led) ────────────────────────────────────────────────

class LedBody(BaseModel):
    color: str = Field("green", pattern=r"^(red|green|blue|yellow|off)$")
    state: str = Field("on", pattern=r"^(on|off|blink)$")


@router.post("/pedestal/{pedestal_id}/led")
async def set_pedestal_led(
    pedestal_id: int,
    body: LedBody = LedBody(),
    db: DBSession = Depends(get_db),
    _: User = Depends(require_control),
):
    """
    Set the pedestal LED state via opta/cmd/led.

    v3.10 — broadcasts a `led_changed` WebSocket event so the dashboard sees
    the change in real time.
    v3.27 — the cabinet LED is single-colour (white): only on/off matters. We
    record the intended state as PENDING and broadcast `confirmed: false`; the
    state flips to confirmed-ON/OFF only when the firmware ACK arrives on
    opta/acks (handled in mqtt_handlers). On a legacy (non-cabinet) pedestal
    there is no ACK channel, so the change is marked confirmed immediately.
    """
    cabinet_id = _get_cabinet_id(db, pedestal_id)
    intended_on = body.state == "on"

    # Persist intended state + pending flag on the pedestal config.
    from ..models.pedestal_config import PedestalConfig
    cfg = db.query(PedestalConfig).filter(PedestalConfig.pedestal_id == pedestal_id).first()
    if cfg is not None:
        cfg.led_on = intended_on
        cfg.led_pending = bool(cabinet_id)          # await ACK only on real cabinets
        if not cabinet_id:
            cfg.led_confirmed_at = datetime.utcnow()  # legacy: no ACK to wait for
        db.commit()

    if cabinet_id:
        mqtt_service.publish(
            "opta/cmd/led",
            json.dumps({"cabinetId": cabinet_id, "color": body.color, "state": body.state}),
        )
    else:
        mqtt_service.publish(
            f"pedestal/{pedestal_id}/cmd/led",
            json.dumps({"color": body.color, "state": body.state}),
        )
    await ws_manager.broadcast({
        "event": "led_changed",
        "data": {
            "pedestal_id": pedestal_id,
            "cabinet_id": cabinet_id or "",
            "color": body.color,
            "state": body.state,
            "on": intended_on,
            "confirmed": not bool(cabinet_id),   # cabinets: confirmed on ACK
            "source": "manual",
            "timestamp": now_iso(),
        },
    })
    return {"status": "led_set", "pedestal_id": pedestal_id, "color": body.color,
            "state": body.state, "on": intended_on, "pending": bool(cabinet_id)}


@router.get("/pedestal/{pedestal_id}/led")
def get_pedestal_led(
    pedestal_id: int,
    db: DBSession = Depends(get_db),
    _: User = Depends(require_any_role),
):
    """v3.27 — current ACK-confirmed LED state for dashboard hydration."""
    from ..models.pedestal_config import PedestalConfig
    cfg = db.query(PedestalConfig).filter(PedestalConfig.pedestal_id == pedestal_id).first()
    if cfg is None:
        return {"pedestal_id": pedestal_id, "on": False, "pending": False, "confirmed_at": None}
    return {
        "pedestal_id": pedestal_id,
        "on": bool(cfg.led_on),
        "pending": bool(cfg.led_pending),
        "confirmed_at": iso_z(cfg.led_confirmed_at),
    }


# ── Direct socket command (admin, no session required) ────────────────────────

class DirectCmdBody(BaseModel):
    # Opta valid actions: activate, stop (maintenance is NOT supported by firmware)
    action: str = Field(..., pattern=r"^(activate|stop)$")


@router.post("/pedestal/{pedestal_id}/socket/{socket_name}/cmd")
async def direct_socket_cmd(
    pedestal_id: int,
    socket_name: str,
    body: DirectCmdBody,
    db: DBSession = Depends(get_db),
    _: User = Depends(require_control),
):
    """
    Send a direct action to a socket outlet (Q1–Q4) via opta/cmd/socket.
    Valid actions: activate, stop.

    Activate is gated on physical plug-in state: the backend refuses to send
    the command if SocketState.connected is False for this socket. This
    prevents the firmware from activating an empty outlet and mirrors what
    the operator sees in the dashboard (yellow pending vs. white idle).

    On stop: also completes any active DB session for this socket.
    """
    if socket_name not in ("Q1", "Q2", "Q3", "Q4"):
        raise HTTPException(status_code=400, detail="socket_name must be one of Q1, Q2, Q3, Q4")

    # v3.30 — standalone cabinets reject all socket control (activate AND stop).
    _require_smart_mode(db, pedestal_id)

    from ..services.mqtt_handlers import _socket_name_to_id
    socket_id = _socket_name_to_id(socket_name)

    if body.action == "activate":
        from ..models.pedestal_config import SocketState
        sock_state = db.query(SocketState).filter(
            SocketState.pedestal_id == pedestal_id,
            SocketState.socket_id == socket_id,
        ).first()
        if not sock_state or not sock_state.connected:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Socket has no plug inserted",
            )
        # v3.30 — an overload alarm no longer blocks re-activation (alarm-only;
        # the NUC never withholds control). The previous auto_stop_pending_ack
        # 409 guard was removed here and in approve_socket.

    # B6 (v3.28) — operator stop disables auto-activate for this socket (before publish).
    # v3.29 — a manual Activate ALSO disables auto-activate: the three socket modes
    # (Auto / Activate / Stop) are mutually exclusive, so explicitly activating (or
    # stopping) is the operator taking manual control and turns Auto off.
    if body.action in ("stop", "activate"):
        await _operator_disable_auto_activate(db, pedestal_id, socket_id)

    cabinet_id = _get_cabinet_id(db, pedestal_id)
    msg_id = str(int(datetime.utcnow().timestamp() * 1000))
    if cabinet_id:
        mqtt_service.publish(
            f"opta/cmd/socket/{socket_name}",
            json.dumps({"msgId": msg_id, "cabinetId": cabinet_id, "action": body.action}),
        )
    else:
        mqtt_service.publish(
            f"pedestal/{pedestal_id}/socket/{socket_name}/command",
            json.dumps({"msgId": msg_id, "action": body.action}),
        )

    # Complete active DB session when stopping (socket_id was resolved above).
    if body.action == "stop":
        active_session = session_service.get_active_for_socket(db, pedestal_id, socket_id)
        if active_session:
            session_service.complete(db, active_session)
            await ws_manager.broadcast({
                "event": "session_completed",
                "data": {
                    "session_id": active_session.id,
                    "pedestal_id": pedestal_id,
                    "socket_id": socket_id,
                    "energy_kwh": active_session.energy_kwh,
                    "customer_id": active_session.customer_id,
                },
            })

    await ws_manager.broadcast({
        "event": "direct_cmd_sent",
        "data": {"pedestal_id": pedestal_id, "target": socket_name, "action": body.action},
    })
    return {"status": "sent", "socket": socket_name, "action": body.action}


@router.post("/pedestal/{pedestal_id}/water/{valve_name}/cmd")
async def direct_water_cmd(
    pedestal_id: int,
    valve_name: str,
    body: DirectCmdBody,
    db: DBSession = Depends(get_db),
    _: User = Depends(require_control),
):
    """
    Send a direct action to a water valve (V1–V2) via opta/cmd/water.
    Valid actions: activate, stop, maintenance.
    On stop: also completes any active DB session for this valve.
    """
    if valve_name not in ("V1", "V2"):
        raise HTTPException(status_code=400, detail="valve_name must be V1 or V2")

    # v3.30 — standalone cabinets reject all valve control.
    _require_smart_mode(db, pedestal_id)

    cabinet_id = _get_cabinet_id(db, pedestal_id)
    msg_id = str(int(datetime.utcnow().timestamp() * 1000))
    if cabinet_id:
        mqtt_service.publish(
            f"opta/cmd/water/{valve_name}",
            json.dumps({"msgId": msg_id, "cabinetId": cabinet_id, "action": body.action}),
        )
    else:
        mqtt_service.publish(
            f"pedestal/{pedestal_id}/water/{valve_name}/command",
            json.dumps({"msgId": msg_id, "action": body.action}),
        )

    # Complete active DB session when stopping
    if body.action == "stop":
        active_session = session_service.get_active_for_socket(db, pedestal_id, None)
        if active_session:
            session_service.complete(db, active_session)
            await ws_manager.broadcast({
                "event": "session_completed",
                "data": {
                    "session_id": active_session.id,
                    "pedestal_id": pedestal_id,
                    "socket_id": None,
                    "water_liters": active_session.water_liters,
                    "customer_id": active_session.customer_id,
                },
            })
        # v3.9 — record operator-initiated manual stop per valve so post-diag
        # auto-open respects the 10-minute cooldown.
        from ..services.mqtt_handlers import last_valve_manual_stop_at
        valve_id = 1 if valve_name == "V1" else 2
        last_valve_manual_stop_at[(pedestal_id, valve_id)] = datetime.utcnow()

    await ws_manager.broadcast({
        "event": "direct_cmd_sent",
        "data": {"pedestal_id": pedestal_id, "target": valve_name, "action": body.action},
    })
    return {"status": "sent", "valve": valve_name, "action": body.action}
