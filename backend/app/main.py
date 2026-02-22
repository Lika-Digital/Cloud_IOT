import asyncio
import logging
import traceback
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from fastapi import FastAPI, Request
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
from .auth.user_database import init_user_db, UserSessionLocal
from .auth.models import User
from .auth.customer_models import BillingConfig
from .auth.password import hash_password

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DEFAULT_ADMIN_EMAIL = "admin@iot-dashboard.local"
DEFAULT_ADMIN_PASSWORD = "admin1234"

# How long a session may stay in 'pending' before being auto-denied
PENDING_TIMEOUT_SECONDS = 15


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
                    logger.info(f"Watchdog: auto-denied stale session {s.id}")
                except Exception as e:
                    logger.warning(f"Watchdog: failed to deny session {s.id}: {e}")
        except Exception as e:
            logger.warning(f"Pending session watchdog error: {e}")
        finally:
            db.close()


# ─── Startup / shutdown ───────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting application...")
    init_db()
    init_user_db()

    from .services.error_log_service import purge_old_logs, log_info, log_error, log_warning

    # Purge stale logs from previous runs
    try:
        purge_old_logs()
    except Exception:
        pass

    # ── Startup check #6: verify DB is reachable ─────────────────────────────
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
            pedestal = Pedestal(
                name="Pedestal 1",
                location="Marina Berth A",
                data_mode="synthetic",
            )
            db.add(pedestal)
            db.commit()
            logger.info("Created default pedestal")

        pedestal_count = db.query(Pedestal).count()
    finally:
        db.close()

    # Seed admin user + billing config
    user_db = UserSessionLocal()
    try:
        admin_exists = bool(user_db.query(User).first())
        if not admin_exists:
            admin = User(
                email=DEFAULT_ADMIN_EMAIL,
                password_hash=hash_password(DEFAULT_ADMIN_PASSWORD),
                role="admin",
            )
            user_db.add(admin)
            user_db.commit()
            logger.info("Created default admin user: %s / %s", DEFAULT_ADMIN_EMAIL, DEFAULT_ADMIN_PASSWORD)

        if not user_db.get(BillingConfig, 1):
            user_db.add(BillingConfig(id=1, kwh_price_eur=0.30, liter_price_eur=0.015))
            user_db.commit()
            logger.info("Created default BillingConfig")

        user_count = user_db.query(User).count()
    finally:
        user_db.close()

    # Start MQTT client
    loop = asyncio.get_event_loop()
    mqtt_service.start(loop)

    # ── Startup check #6: summarise what we found ────────────────────────────
    log_info(
        "system", "startup",
        f"Application started — {pedestal_count} pedestal(s), {user_count} operator user(s), "
        f"MQTT → {settings.mqtt_broker_host}:{settings.mqtt_broker_port}, "
        f"pending timeout {PENDING_TIMEOUT_SECONDS}s",
    )

    # Start background tasks
    cleanup_task  = asyncio.create_task(_hourly_log_purge())
    watchdog_task = asyncio.create_task(_pending_session_watchdog())

    yield

    # Shutdown
    logger.info("Shutting down...")
    cleanup_task.cancel()
    watchdog_task.cancel()
    mqtt_service.stop()
    simulator_manager.stop()
    try:
        log_info("system", "main", "Application stopped cleanly")
    except Exception:
        pass


# ─── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Smart Pedestal IoT API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Global exception handler ────────────────────────────────────────────────

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Catch all unhandled 500 errors, log them, return JSON."""
    path = request.url.path
    tb = traceback.format_exc()
    logger.error(f"Unhandled exception on {path}: {exc}\n{tb}")
    try:
        from .services.error_log_service import log_error
        log_error(
            "system", "api",
            f"Unhandled exception: {type(exc).__name__} on {path}",
            details=tb[:2000],
        )
    except Exception:
        pass
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "path": path},
    )


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


@app.get("/health")
def health():
    return {
        "status": "ok",
        "mqtt_connected": mqtt_service.is_connected,
        "simulator_running": simulator_manager.is_running,
    }
