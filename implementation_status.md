# Implementation Status — Cloud_IOT CV Feature Extension

Last updated: 2026-04-03 (Sections 8-10 complete)

## Sections

- [x] Section 1: Frame Buffer Service
- [x] Section 2: Model Setup Script
- [x] Section 3: OpenVINO Inference Layer
- [x] Section 4: Training Data Pipeline
- [x] Section 5: Storage Monitor
- [x] Section 6: Updated Analyze and Match Endpoints
- [x] Section 7: New Berth DB Columns
- [x] Section 8: Sector Configuration UI
- [x] Section 9: Runtime UI Updates
- [x] Section 10: Storage Warning Banner + Polling

## What was done

### Section 1 — Frame Buffer Service
- Created `backend/app/services/frame_buffer.py`
- Singleton `_buffer: dict[int, bytes]` keyed by pedestal_id
- Background coroutine `run_frame_buffer()` polls every 10s from all reachable cameras
- Wired into `main.py` lifespan as `asyncio.create_task(run_frame_buffer())`

### Section 2 — Model Setup Script
- Created `backend/setup_openvino_models.py` (NUC-only, idempotent)
  - Step 1: YOLOv8n → OpenVINO IR via ultralytics export
  - Step 2: MobileNetV3-Small Re-ID head → ONNX → OpenVINO IR
- Created `backend/app/services/model_paths.py` — platform-aware model directory resolver

### Section 3 — OpenVINO Inference Layer
- Created `backend/app/services/yolo_openvino.py` — `YoloOVDetector` class
  - All OpenVINO/numpy imports lazy inside `__init__` and `detect()`
  - Falls back to `{"occupied": None, ...}` when unavailable
  - Detects COCO class 8 (boat) above confidence threshold
- Created `backend/app/services/reid_openvino.py` — `ReidOVMatcher` class
  - 128-dim L2-normalised embedding extraction
  - `save_embedding()` / `load_embedding()` to .npy files
  - `cosine_similarity()` via scipy with numpy fallback
- Created `backend/app/services/cv_services.py` — module-level singletons

### Section 4 — Training Data Pipeline
- Created `backend/app/services/training_data.py`
  - `save_crop()` — JPEG + JSON metadata, timestamp-based filenames
  - `confirm_crop()` — move to confirmed/ or rejected/ subfolder
  - Directory layout: training_data/{occupied,empty}/{confirmed,rejected}/, match_samples/

### Section 5 — Storage Monitor
- Created `backend/app/services/storage_monitor.py`
  - `get_training_storage_status()` → {size_gb, max_gb, percent_used, alarm_active}
  - `run_storage_monitor()` — 5-min background loop, broadcasts WebSocket alarm on state change
- Added `GET /api/system/training-storage` to `system_health.py`
- Wired `run_storage_monitor()` into `main.py` lifespan

### Section 6 — Updated Analyze and Match Endpoints
- Updated `POST /api/admin/berths/{id}/analyze`:
  - Tries frame buffer first, falls back to live grab
  - Crops to detection zone if configured
  - Tries YOLOv8n OpenVINO, falls back to existing Laplacian
  - Saves training crop via async fire-and-forget
  - Returns `confidence` field
- Added `POST /api/admin/berths/{id}/match`:
  - Gets frame → crop → Re-ID embedding → cosine similarity vs stored embedding
  - Returns `{match_score, timestamp}`
- Added `POST /api/admin/berths/{id}/sample-embedding`:
  - Accepts multipart file upload, extracts Re-ID embedding, saves .npy, updates DB

### Section 7 — New Berth DB Columns
- Added `sample_embedding_path: String(500)` and `sample_updated_at: DateTime` to `Berth` model
- Added migrations to `_migrate_user_schema()` in `user_database.py`
- Added fields to `BerthOut` schema and `_berth_to_out()` helper
- Added `confidence: float = 0.0` to `BerthOut`

### Section 8 — Sector Configuration UI
- Added zone fields to `BerthConfigUpdate` schema (zone_x1/y1/x2/y2, use_detection_zone)
- Added zone fields to `BerthOut` schema and `_berth_to_out()` helper
- Added `GET /api/admin/pedestals/{id}/latest-frame` — frame buffer → base64 JPEG
- Added `POST /api/admin/berths/{id}/confirm-crop` — operator training data feedback
- Updated `frontend/src/api/berths.ts`: BerthOut extended with zone + embedding + confidence fields; new API functions; StorageStatus type
- Updated `frontend/src/store/index.ts`: BerthStatus extended with new fields
- Created `frontend/src/components/berths/SectorConfigModal.tsx`:
  - Canvas drawing area with image background and drag-to-resize zone rectangle
  - Right panel: zone coordinate display, use_detection_zone toggle, sample embedding upload
  - Save/Reset buttons

### Section 9 — Runtime UI Updates
- `handleAnalyze` shows: `⛵ Occupied (87.3% confidence) — analyzed 14:32:11`
- `crop_path` from analyze response enables operator confirmation
- `handleMatchShip` + Match Ship button (disabled when not occupied / no embedding)
- Match result displayed inline: `Ship match: 94.2% — checked 14:32:15`
- Thumbs up 👍 / 👎 buttons for operator crop confirmation; disappear after click
- `handleConfirmCrop` calls `confirmCrop()` (fire-and-forget, non-blocking)
- "Sectors" button in each berth row opens SectorConfigModal

### Section 10 — Storage Warning Banner + Polling
- Storage polling every 5 minutes via `getStorageStatus()` in `useEffect`
- Amber warning banner at page top when `alarm_active` is true
- Compact storage indicator in page header (size_gb / max_gb) always visible when data loaded
- Storage state stored in `storageAlarm: StorageStatus | null`

## Notes

- Dev machine: 32-bit Python 3.13 on Windows — all ML imports lazy/try-except
- Production: Ubuntu 24.04 NUC with 64-bit Python — all ML packages available
- All commits go to `develop` branch
- 124/124 backend tests pass
