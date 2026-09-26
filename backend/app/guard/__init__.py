"""Guard — control and query layer inside the backend.

Detection, ffmpeg and recording live in `guard_worker/` (cloud-iot-guard.service). What
lives here is the backend's half: models, REST router, desired-state service, plus the two
modules SHARED with the worker and the probe:

  * `pipeline.py`   — the per-frame path (crop -> visibility -> detect -> band)
  * `alarm_rule.py` — the alarm decision, deliberately separate from detection

Those two must import stdlib + numpy + PIL only, so the probe can use them from the
staging venv without FastAPI or SQLAlchemy present. `test_guard_import_isolation.py`
enforces it.
"""
