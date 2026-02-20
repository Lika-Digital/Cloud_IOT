from pydantic import BaseModel
from typing import Optional


class PowerPayload(BaseModel):
    watts: float
    kwh_total: float


class WaterPayload(BaseModel):
    lpm: float
    total_liters: float


class HeartbeatPayload(BaseModel):
    timestamp: str
    online: bool


class SocketStatusPayload(BaseModel):
    status: str  # "connected" | "disconnected"


class WSMessage(BaseModel):
    event: str
    data: dict
    pedestal_id: Optional[int] = None
