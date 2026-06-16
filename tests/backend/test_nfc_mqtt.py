"""NFC MQTT activation + webhook tests (v3.26).

Exercises the UserPluggedIn / OutletActivated NFC hooks and the ERP webhook
wiring by calling the handlers directly with a TestSession db, patching the
fire-and-forget collaborators.
"""
import asyncio
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from unittest.mock import patch, AsyncMock

TEST_DB = "sqlite:///./tests/test_pedestal.db"
_engine = create_engine(TEST_DB, connect_args={"check_same_thread": False})
_S = sessionmaker(autocommit=False, autoflush=False, bind=_engine)

CAB = "TST_NFC_MQTT"


@pytest.fixture(scope="module")
def mqtt_pid(client, auth_headers):
    """Real pedestal with cabinet id + 4 socket_configs for MQTT NFC tests."""
    r = client.post("/api/pedestals/", json={
        "name": "NFC MQTT Pedestal", "location": "Dock", "data_mode": "real",
    }, headers=auth_headers)
    assert r.status_code in (200, 201), r.text
    pid = r.json()["id"]
    from app.models.pedestal_config import PedestalConfig
    from app.models.socket_config import SocketConfig
    db = _S()
    try:
        cfg = db.query(PedestalConfig).filter(PedestalConfig.pedestal_id == pid).first()
        if cfg is None:
            cfg = PedestalConfig(pedestal_id=pid); db.add(cfg)
        cfg.opta_client_id = CAB
        for sid in (1, 2, 3, 4):
            if db.query(SocketConfig).filter(
                SocketConfig.pedestal_id == pid, SocketConfig.socket_id == sid).first() is None:
                db.add(SocketConfig(pedestal_id=pid, socket_id=sid, auto_activate=True))
        db.commit()
    finally:
        db.close()
    return pid


def _set_auto(pid, value):
    from app.models.socket_config import SocketConfig
    db = _S()
    try:
        for s in db.query(SocketConfig).filter(SocketConfig.pedestal_id == pid).all():
            s.auto_activate = value
        db.commit()
    finally:
        db.close()


def _clear(pid):
    from app.models.nfc_pending_session import NfcPendingSession
    from app.models.session import Session
    db = _S()
    try:
        db.query(NfcPendingSession).filter(NfcPendingSession.cabinet_id == CAB).delete()
        db.query(Session).filter(Session.pedestal_id == pid).delete()
        db.commit()
    finally:
        db.close()


def _add_pending(socket_id, user_id, status="pending", age_min=0, ttl_min=5):
    from app.models.nfc_pending_session import NfcPendingSession
    db = _S()
    try:
        now = datetime.utcnow()
        rec = NfcPendingSession(
            nfc_tag_id=f"T-{socket_id}", user_id=user_id, cabinet_id=CAB, socket_id=socket_id,
            created_at=now - timedelta(minutes=age_min),
            expires_at=now - timedelta(minutes=age_min) + timedelta(minutes=ttl_min),
            status=status)
        db.add(rec); db.commit(); db.refresh(rec)
        return rec.id
    finally:
        db.close()


def _pending_status(rec_id):
    from app.models.nfc_pending_session import NfcPendingSession
    db = _S()
    try:
        return db.get(NfcPendingSession, rec_id).status
    finally:
        db.close()


def _run_plugged_in(pid, socket="Q1"):
    from app.services.mqtt_handlers import _handle_event_user_plugged_in
    db = _S()
    try:
        asyncio.run(_handle_event_user_plugged_in(db, pid, socket, "POWER", {}))
    finally:
        db.close()


# ── UserPluggedIn NFC paths ───────────────────────────────────────────────────

def test_valid_pending_triggers_one_shot_activate(client, mqtt_pid):
    _clear(mqtt_pid); _set_auto(mqtt_pid, False)  # NFC mode
    rec_id = _add_pending("Q1", "erp-1")
    with (
        patch("app.services.mqtt_handlers.ws_manager.broadcast", AsyncMock()),
        patch("app.services.mqtt_handlers._maybe_auto_activate", AsyncMock()) as maa,
    ):
        _run_plugged_in(mqtt_pid, "Q1")
    assert maa.called, "one-shot activate should fire for a valid NFC pending"
    assert _pending_status(rec_id) == "activated"


def test_expired_pending_blocks_activation(client, mqtt_pid):
    _clear(mqtt_pid); _set_auto(mqtt_pid, False)  # NFC mode
    rec_id = _add_pending("Q1", "erp-x", age_min=10)  # expired (created 10m ago, ttl 5m)
    with (
        patch("app.services.mqtt_handlers.ws_manager.broadcast", AsyncMock()),
        patch("app.services.mqtt_handlers._maybe_auto_activate", AsyncMock()) as maa,
    ):
        _run_plugged_in(mqtt_pid, "Q1")
    assert not maa.called, "expired pending must not activate"
    assert _pending_status(rec_id) == "expired"


def test_nfc_mode_no_pending_blocks(client, mqtt_pid):
    _clear(mqtt_pid); _set_auto(mqtt_pid, False)  # NFC mode, no pending
    with (
        patch("app.services.mqtt_handlers.ws_manager.broadcast", AsyncMock()),
        patch("app.services.mqtt_handlers._maybe_auto_activate", AsyncMock()) as maa,
    ):
        _run_plugged_in(mqtt_pid, "Q2")
    assert not maa.called, "NFC mode without a pending scan must not activate"


def test_qr_mode_unchanged_autoactivate(client, mqtt_pid):
    _clear(mqtt_pid); _set_auto(mqtt_pid, True)  # QR mode
    with (
        patch("app.services.mqtt_handlers.ws_manager.broadcast", AsyncMock()),
        patch("app.services.mqtt_handlers._maybe_auto_activate", AsyncMock()) as maa,
    ):
        _run_plugged_in(mqtt_pid, "Q3")
    assert maa.called, "QR mode with auto_activate=True must keep auto-activating"


# ── OutletActivated attaches NFC user ─────────────────────────────────────────

def test_outlet_activated_attaches_nfc_user(client, mqtt_pid):
    _clear(mqtt_pid)
    _add_pending("Q1", "erp-attach", status="activated")  # already marked activated
    from app.services.mqtt_handlers import _handle_event_outlet_activated
    from app.models.session import Session
    with (
        patch("app.services.mqtt_handlers.ws_manager.broadcast", AsyncMock()),
        patch("app.services.erp_webhook.post_erp_event", AsyncMock()),
    ):
        db = _S()
        try:
            asyncio.run(_handle_event_outlet_activated(db, mqtt_pid, "Q1", "POWER", {}))
        finally:
            db.close()
    db = _S()
    try:
        s = db.query(Session).filter(Session.pedestal_id == mqtt_pid,
                                     Session.socket_id == 1, Session.status == "active").first()
        assert s is not None and s.nfc_user_id == "erp-attach"
    finally:
        db.close()
    _clear(mqtt_pid)


# ── Webhook wiring ────────────────────────────────────────────────────────────

def test_webhook_fires_on_activate_when_url_set(client, mqtt_pid):
    _clear(mqtt_pid)
    from app.config import settings
    from app.services.mqtt_handlers import _handle_event_outlet_activated
    prev = settings.erp_webhook_url
    settings.erp_webhook_url = "https://erp.example/webhook"
    try:
        with (
            patch("app.services.mqtt_handlers.ws_manager.broadcast", AsyncMock()),
            patch("app.services.erp_webhook.post_erp_event", AsyncMock()) as post,
        ):
            db = _S()
            try:
                asyncio.run(_handle_event_outlet_activated(db, mqtt_pid, "Q2", "POWER", {}))
            finally:
                db.close()
        assert post.called, "activate webhook should fire when ERP_WEBHOOK_URL is set"
    finally:
        settings.erp_webhook_url = prev
        _clear(mqtt_pid)


def test_webhook_not_called_when_url_unset(client, mqtt_pid):
    _clear(mqtt_pid)
    from app.config import settings
    from app.services.mqtt_handlers import _handle_event_outlet_activated
    prev = settings.erp_webhook_url
    settings.erp_webhook_url = None
    try:
        with (
            patch("app.services.mqtt_handlers.ws_manager.broadcast", AsyncMock()),
            patch("app.services.erp_webhook.post_erp_event", AsyncMock()) as post,
        ):
            db = _S()
            try:
                asyncio.run(_handle_event_outlet_activated(db, mqtt_pid, "Q3", "POWER", {}))
            finally:
                db.close()
        assert not post.called, "no webhook when ERP_WEBHOOK_URL is unset"
    finally:
        settings.erp_webhook_url = prev
        _clear(mqtt_pid)


def test_webhook_failure_does_not_block(client, mqtt_pid):
    """post_erp_event must swallow errors; the handler completes regardless."""
    from app.config import settings
    from app.services import erp_webhook
    prev = settings.erp_webhook_url
    settings.erp_webhook_url = "https://erp.invalid/webhook"
    try:
        async def _boom(*a, **k):
            raise RuntimeError("network down")
        # build a payload then ensure post_erp_event itself never raises out
        with patch("httpx.AsyncClient.post", AsyncMock(side_effect=RuntimeError("down"))):
            asyncio.run(erp_webhook.post_erp_event({"event": "x", "session_id": 1}))
    finally:
        settings.erp_webhook_url = prev
