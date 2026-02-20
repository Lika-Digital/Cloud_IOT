# Smart Pedestal IoT Management Application

A full-stack IoT monitoring and session management application for a smart marina/campsite pedestal with 4 electricity sockets and 1 water meter.

## Architecture

```
Simulator (Python/paho-mqtt)
        │ MQTT publish
        ▼
Mosquitto Broker (Docker, :1883)
        │ MQTT subscribe
        ▼
FastAPI Backend (:8000)
  ├── SQLite DB (SQLAlchemy)
  ├── MQTT Client (paho, background thread → asyncio bridge)
  ├── WebSocket Manager (broadcast to React clients)
  └── REST API (sessions, controls, analytics, predictions)
        │ WebSocket + REST
        ▼
React Frontend (:5173)
  ├── Zustand store (real-time state)
  ├── Recharts (consumption charts + prediction overlay)
  └── Configuration panel (synthetic vs. real pedestal)
```

## Quick Start

### Prerequisites
- Docker & Docker Compose
- Python 3.12+
- Node.js 18+

### 1. Start MQTT Broker

```bash
docker compose up -d
```

### 2. Start Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp ../.env.example .env
uvicorn app.main:app --reload
```

### 3. Start Frontend

```bash
cd frontend
npm install
npm run dev
```

### 4. Open Dashboard

Navigate to http://localhost:5173

In Settings, select **Synthetic Data** and click Apply to start the simulator.

## MQTT Topic Map

| Topic | Direction | Payload |
|---|---|---|
| `pedestal/{id}/socket/{1-4}/status` | Pedestal → Backend | `"connected"` \| `"disconnected"` |
| `pedestal/{id}/socket/{1-4}/power` | Pedestal → Backend | `{"watts": float, "kwh_total": float}` |
| `pedestal/{id}/socket/{1-4}/control` | Backend → Pedestal | `"allow"` \| `"deny"` \| `"stop"` |
| `pedestal/{id}/water/flow` | Pedestal → Backend | `{"lpm": float, "total_liters": float}` |
| `pedestal/{id}/water/control` | Backend → Pedestal | `"allow"` \| `"deny"` \| `"stop"` |
| `pedestal/{id}/heartbeat` | Pedestal → Backend | `{"timestamp": str, "online": bool}` |

## Session Flow

1. Plug detected → MQTT "connected"
2. Backend creates Session (status: pending)
3. Dashboard shows Allow/Deny card
4. Operator clicks Allow → MQTT "allow" → session active
5. Live power readings displayed
6. Operator clicks Stop → session completed, totals calculated

## Tech Stack

- **Backend**: Python 3.12, FastAPI, Uvicorn, SQLAlchemy 2.0, paho-mqtt 2.x
- **ML**: scikit-learn LinearRegression
- **Broker**: Eclipse Mosquitto 2.0 (Docker)
- **Frontend**: React 18, TypeScript, Vite, Zustand, Recharts, Tailwind CSS
