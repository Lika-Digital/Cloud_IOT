"""Guard worker — runs as cloud-iot-guard.service, NOT inside the backend process.

Deliberately outside `backend/app/` so it never imports FastAPI or SQLAlchemy: it owns
ffmpeg, inference and recording files, publishes over MQTT, and never opens a database.
The backend remains the only DB writer. See docs/guard_b1_design.md.
"""
