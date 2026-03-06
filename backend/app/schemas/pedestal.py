from pydantic import BaseModel
from typing import Optional


class PedestalBase(BaseModel):
    name: str
    location: Optional[str] = None
    ip_address: Optional[str] = None
    camera_ip: Optional[str] = None
    data_mode: str = "real"
    initialized: bool = False
    mobile_enabled: bool = False
    ai_enabled: bool = False


class PedestalCreate(PedestalBase):
    pass


class PedestalUpdate(BaseModel):
    name: Optional[str] = None
    location: Optional[str] = None
    ip_address: Optional[str] = None
    camera_ip: Optional[str] = None
    data_mode: Optional[str] = None
    initialized: Optional[bool] = None
    mobile_enabled: Optional[bool] = None
    ai_enabled: Optional[bool] = None


class PedestalResponse(PedestalBase):
    id: int

    model_config = {"from_attributes": True}
