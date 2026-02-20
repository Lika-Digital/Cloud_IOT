from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class SensorReadingResponse(BaseModel):
    id: int
    session_id: Optional[int] = None
    pedestal_id: int
    socket_id: Optional[int] = None
    type: str
    value: float
    unit: str
    timestamp: datetime

    model_config = {"from_attributes": True}
