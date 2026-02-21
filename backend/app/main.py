import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .database import init_db, SessionLocal
from .models.pedestal import Pedestal
from .services.mqtt_client import mqtt_service
from .services.simulator_manager import simulator_manager
from .routers import pedestals, sessions, controls, analytics, predictions, websocket, camera, diagnostics
from .routers import auth as auth_router
from .auth.user_database import init_user_db, UserSessionLocal
from .auth.models import User
from .auth.password import hash_password

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DEFAULT_ADMIN_EMAIL = "admin@iot-dashboard.local"
DEFAULT_ADMIN_PASSWORD = "admin1234"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting application...")
    init_db()
    init_user_db()

    # Seed default pedestal if none exist
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
    finally:
        db.close()

    # Seed default admin user if none exist
    user_db = UserSessionLocal()
    try:
        if not user_db.query(User).first():
            admin = User(
                email=DEFAULT_ADMIN_EMAIL,
                password_hash=hash_password(DEFAULT_ADMIN_PASSWORD),
                role="admin",
            )
            user_db.add(admin)
            user_db.commit()
            logger.info(
                "Created default admin user: %s / %s",
                DEFAULT_ADMIN_EMAIL,
                DEFAULT_ADMIN_PASSWORD,
            )
    finally:
        user_db.close()

    # Start MQTT client with current event loop
    loop = asyncio.get_event_loop()
    mqtt_service.start(loop)

    yield

    # Shutdown
    logger.info("Shutting down...")
    mqtt_service.stop()
    simulator_manager.stop()


app = FastAPI(
    title="Smart Pedestal IoT API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router.router)
app.include_router(pedestals.router)
app.include_router(sessions.router)
app.include_router(controls.router)
app.include_router(analytics.router)
app.include_router(predictions.router)
app.include_router(websocket.router)
app.include_router(camera.router)
app.include_router(diagnostics.router)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "mqtt_connected": mqtt_service.is_connected,
        "simulator_running": simulator_manager.is_running,
    }
