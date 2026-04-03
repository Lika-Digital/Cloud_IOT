from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class SessionResponse(BaseModel):
    id: int
    pedestal_id: int
    socket_id: Optional[int] = None
    type: str
    status: str
    started_at: datetime
    ended_at: Optional[datetime] = None
    energy_kwh: Optional[float] = None
    water_liters: Optional[float] = None
    customer_id: Optional[int] = None
    deny_reason: Optional[str] = None
    # customer_name is not a DB column — populated by endpoints that join customer data
    # GAP-FE-BE: field required by frontend Session interface (store/index.ts)
    customer_name: Optional[str] = None

    model_config = {"from_attributes": True}
