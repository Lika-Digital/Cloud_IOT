import asyncio
import logging
import traceback
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from .config import settings
from .database import init_db, SessionLocal, engine
from .models.pedestal import Pedestal
from .models.session import Session as SessionModel
from .services.mqtt_client import mqtt_service
from .services.simulator_manager import simulator_manager
from .services.session_service import session_service
from .services.websocket_manager import ws_manager
from .routers import pedestals, sessions, controls, analytics, predictions, websocket, camera, diagnostics
from .routers import auth as auth_router
from .routers import customer_auth, customer_sessions, customer_invoices, billing, chat, system_health
from .routers import alarms as alarms_router
from .routers import customer_alarms
from .routers import contracts as contracts_router
from .routers import service_orders as service_orders_router
from .routers import reviews as reviews_router
from .routers import berths as berths_router
from .auth.user_database import init_user_db, UserSessionLocal
from .auth.models import User
from .auth.customer_models import BillingConfig
from .auth.contract_models import ContractTemplate
from .auth.berth_models import Berth
from .auth.password import hash_password
from .middleware.security_middleware import SecurityMiddleware

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DEFAULT_ADMIN_EMAIL = "admin@iot-dashboard.local"
DEFAULT_ADMIN_PASSWORD = "admin1234"

PENDING_TIMEOUT_SECONDS = 15
COMM_LOSS_TIMEOUT_SECONDS = 60


# ─── Background tasks ────────────────────────────────────────────────────────

async def _hourly_log_purge():
    """Purge error logs older than 7 days, every hour."""
    while True:
        await asyncio.sleep(3600)
        try:
            from .services.error_log_service import purge_old_logs
            purge_old_logs()
        except Exception as e:
            logger.warning(f"Hourly log purge failed: {e}")


async def _pending_session_watchdog():
    """
    Every 10 s: find sessions stuck in 'pending' longer than PENDING_TIMEOUT_SECONDS
    and auto-deny them so sockets are not held indefinitely.
    """
    from .services.error_log_service import log_warning
    while True:
        await asyncio.sleep(10)
        cutoff = datetime.utcnow() - timedelta(seconds=PENDING_TIMEOUT_SECONDS)
        db = SessionLocal()
        try:
            stale = (
                db.query(SessionModel)
                .filter(SessionModel.status == "pending", SessionModel.started_at < cutoff)
                .all()
            )
            for s in stale:
                try:
                    session_service.deny(db, s, reason=f"Auto-denied: no operator response within {PENDING_TIMEOUT_SECONDS}s")
                    await ws_manager.broadcast({
                        "event": "session_updated",
                        "data": {
                            "session_id": s.id,
                            "pedestal_id": s.pedestal_id,
                            "socket_id": s.socket_id,
                            "type": s.type,
                            "status": "denied",
                            "customer_id": s.customer_id,
                            "deny_reason": f"Auto-denied: no operator response within {PENDING_TIMEOUT_SECONDS}s",
                        },
                    })
                    log_warning(
                        "system", "watchdog",
                        f"Session {s.id} auto-denied (pedestal={s.pedestal_id}, "
                        f"socket={s.socket_id}) — pending >{PENDING_TIMEOUT_SECONDS}s",
                    )
                except Exception as e:
                    logger.warning(f"Watchdog: failed to deny session {s.id}: {e}")
        except Exception as e:
            logger.warning(f"Pending session watchdog error: {e}")
        finally:
            db.close()


async def _comm_loss_watchdog():
    """
    Every 30 s: check each known pedestal against its last-heartbeat timestamp.
    If no heartbeat received in COMM_LOSS_TIMEOUT_SECONDS, raise a comm_loss alarm
    (deduplicated — only one active comm_loss alarm per pedestal at a time).
    When the pedestal recovers (heartbeat seen again), the alarm stays until
    the operator acknowledges it.
    """
    from .services.error_log_service import log_warning
    from .services.alarm_service import trigger_alarm, get_active_alarms
    from .services.mqtt_handlers import last_heartbeat

    while True:
        await asyncio.sleep(30)
        try:
            db = SessionLocal()
            try:
                pedestal_ids = [p.id for p in db.query(Pedestal).all()]
            finally:
                db.close()

            now = datetime.utcnow()
            cutoff = now - timedelta(seconds=COMM_LOSS_TIMEOUT_SECONDS)

            # Pedestals already carrying an active comm_loss alarm
            active = get_active_alarms()
            already_alarmed = {
                a.pedestal_id for a in active
                if a.alarm_type == "comm_loss" and a.pedestal_id is not None
            }

            for pid in pedestal_ids:
                last_hb = last_heartbeat.get(pid)
                if last_hb is None:
                    continue  # never received a heartbeat — pedestal not yet active
                if last_hb < cutoff and pid not in already_alarmed:
                    trigger_alarm(
                        alarm_type="comm_loss",
                        source="sensor_auto",
                        message=f"Pedestal {pid}: no heartbeat for >{COMM_LOSS_TIMEOUT_SECONDS}s",
                        pedestal_id=pid,
                        deduplicate=True,
                    )
                    log_warning(
                        "hw", "comm_loss_watchdog",
                        f"Pedestal {pid} communication loss — no heartbeat in {COMM_LOSS_TIMEOUT_SECONDS}s",
                    )
        except Exception as e:
            logger.warning(f"Comm loss watchdog error: {e}")


# ─── Startup / shutdown ───────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting application...")
    init_db()
    init_user_db()

    from .services.error_log_service import purge_old_logs, log_info, log_error

    try:
        purge_old_logs()
    except Exception:
        pass

    # Startup check: verify DB is reachable
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        log_info("system", "startup", "Database connectivity OK")
    except Exception as e:
        log_error("system", "startup", f"Database connectivity FAILED on startup: {e}", exc=e)

    # Seed default pedestal
    db = SessionLocal()
    try:
        if not db.query(Pedestal).first():
            db.add(Pedestal(name="Pedestal 1", location="Marina Berth A", data_mode="synthetic"))
            db.commit()
            logger.info("Created default pedestal")
        pedestal_count = db.query(Pedestal).count()
    finally:
        db.close()

    # Seed admin user + billing config + default contract template
    user_db = UserSessionLocal()
    try:
        if not user_db.query(User).first():
            user_db.add(User(
                email=DEFAULT_ADMIN_EMAIL,
                password_hash=hash_password(DEFAULT_ADMIN_PASSWORD),
                role="admin",
            ))
            user_db.commit()
            logger.info("Created default admin: %s / %s", DEFAULT_ADMIN_EMAIL, DEFAULT_ADMIN_PASSWORD)
        if not user_db.get(BillingConfig, 1):
            user_db.add(BillingConfig(id=1, kwh_price_eur=0.30, liter_price_eur=0.015))
            user_db.commit()
        # Seed default berths (3 berths for the pilot)
        if not user_db.query(Berth).first():
            user_db.add(Berth(
                name="Yearly Contract Berth 1",
                pedestal_id=1,
                status="free",
                detected_status="free",
                video_source="Berth Full.mp4",
                reference_image="Full_Berth.jpg",
                detect_conf_threshold=0.30,
                match_threshold=0.50,
            ))
            user_db.add(Berth(
                name="Yearly Contract Berth 2",
                pedestal_id=2,
                status="free",
                detected_status="free",
                video_source="Berth empty.mp4",
                reference_image=None,
                detect_conf_threshold=0.30,
                match_threshold=0.50,
            ))
            user_db.add(Berth(
                name="Transit Berth",
                pedestal_id=None,
                status="free",
                detected_status="free",
                video_source=None,
                reference_image=None,
                detect_conf_threshold=0.30,
                match_threshold=0.50,
            ))
            user_db.commit()
            logger.info("Seeded 3 default berths (berth 1: ref=Full_Berth.jpg)")

        if not user_db.query(ContractTemplate).first():
            user_db.add(ContractTemplate(
                title="Marina Portorož – Berth Service Agreement",
                validity_days=365,
                notify_on_register=True,
                active=True,
                body=(
                    "BERTH SERVICE AGREEMENT\n\n"
                    "This Berth Service Agreement ('Agreement') is entered into between Marina Portorož "
                    "(Cesta solinarjev 8, 6320 Portorož, Slovenia) and the Customer identified above.\n\n"
                    "1. SERVICES\n"
                    "Marina Portorož provides the following services at its pedestals: "
                    "electricity supply (4 sockets per pedestal, metered in kWh), "
                    "fresh water supply (metered in litres), Wi-Fi access, and upon request: "
                    "crane services, engine checks, hull cleaning, diver services, battery checks, "
                    "and electrical checks.\n\n"
                    "2. FEES\n"
                    "Electricity is charged per kWh consumed. Water is charged per litre consumed. "
                    "Current prices are displayed in the Marina IoT portal. Service fees for crane, "
                    "engine, hull, and diver services are quoted separately upon request. "
                    "All prices are exclusive of VAT unless otherwise stated.\n\n"
                    "3. CUSTOMER OBLIGATIONS\n"
                    "The Customer agrees to: (a) use only properly rated connectors; "
                    "(b) not exceed the rated current for any socket; "
                    "(c) report any malfunctions immediately to marina staff; "
                    "(d) comply with all marina regulations and the Slovenian Maritime Act.\n\n"
                    "4. LIABILITY\n"
                    "Marina Portorož is not liable for interruptions of electricity or water supply "
                    "due to technical faults, maintenance, or force majeure. "
                    "The Customer is liable for damage caused by improper use.\n\n"
                    "5. TERM & TERMINATION\n"
                    "This Agreement is valid for the period specified above. "
                    "Either party may terminate with 24 hours written notice.\n\n"
                    "6. GOVERNING LAW\n"
                    "This Agreement is governed by the laws of the Republic of Slovenia. "
                    "Disputes shall be resolved before the competent court in Koper, Slovenia.\n\n"
                    "By signing below, the Customer confirms they have read, understood, "
                    "and agree to be bound by the terms of this Agreement."
                ),
            ))
            user_db.commit()
            logger.info("Seeded default contract template: Marina Portorož – Berth Service Agreement")
        user_count = user_db.query(User).count()
    finally:
        user_db.close()

    # Start MQTT
    loop = asyncio.get_event_loop()
    mqtt_service.start(loop)

    log_info(
        "system", "startup",
        f"Application started — {pedestal_count} pedestal(s), {user_count} operator user(s), "
        f"MQTT → {settings.mqtt_broker_host}:{settings.mqtt_broker_port}, "
        f"pending timeout {PENDING_TIMEOUT_SECONDS}s, comm-loss timeout {COMM_LOSS_TIMEOUT_SECONDS}s",
    )

    from .services.berth_analyzer import run_berth_analysis
    cleanup_task    = asyncio.create_task(_hourly_log_purge())
    watchdog_task   = asyncio.create_task(_pending_session_watchdog())
    comm_loss_task  = asyncio.create_task(_comm_loss_watchdog())
    berth_task      = asyncio.create_task(run_berth_analysis())

    yield

    logger.info("Shutting down...")
    cleanup_task.cancel()
    watchdog_task.cancel()
    comm_loss_task.cancel()
    berth_task.cancel()
    mqtt_service.stop()
    simulator_manager.stop()
    try:
        log_info("system", "main", "Application stopped cleanly")
    except Exception:
        pass


# ─── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(title="Smart Pedestal IoT API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SecurityMiddleware)


# ─── Global exception handler ────────────────────────────────────────────────

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    # Let FastAPI handle HTTPException with its proper status code
    if isinstance(exc, HTTPException):
        raise exc
    path = request.url.path
    tb = traceback.format_exc()
    logger.error(f"Unhandled exception on {path}: {exc}\n{tb}")
    try:
        from .services.error_log_service import log_error
        log_error("system", "api", f"Unhandled exception: {type(exc).__name__} on {path}", details=tb[:4000])
    except Exception:
        pass
    return JSONResponse(status_code=500, content={"detail": "Internal server error", "path": path})


# ─── Routers ─────────────────────────────────────────────────────────────────

app.include_router(auth_router.router)
app.include_router(pedestals.router)
app.include_router(sessions.router)
app.include_router(controls.router)
app.include_router(analytics.router)
app.include_router(predictions.router)
app.include_router(websocket.router)
app.include_router(camera.router)
app.include_router(diagnostics.router)
app.include_router(customer_auth.router)
app.include_router(customer_sessions.router)
app.include_router(customer_invoices.router)
app.include_router(billing.router)
app.include_router(chat.router)
app.include_router(system_health.router)
app.include_router(alarms_router.router)
app.include_router(customer_alarms.router)
app.include_router(contracts_router.router)
app.include_router(service_orders_router.router)
app.include_router(reviews_router.router)
app.include_router(berths_router.router)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "mqtt_connected": mqtt_service.is_connected,
        "simulator_running": simulator_manager.is_running,
    }
