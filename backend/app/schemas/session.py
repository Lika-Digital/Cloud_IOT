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
    # external ERP/myMarina user id (session.nfc_user_id), kept separate from the
    # internal customer_id FK. Exposed so an ERP can correlate an active session
    # to the user id it sent us via POST /api/nfc/scan.
    nfc_user_id: Optional[str] = None
    deny_reason: Optional[str] = None
    # customer_name is not a DB column — populated by endpoints that join customer data
    # GAP-FE-BE: field required by frontend Session interface (store/index.ts)
    customer_name: Optional[str] = None

    model_config = {"from_attributes": True}
