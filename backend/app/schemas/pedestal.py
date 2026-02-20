from pydantic import BaseModel
from typing import Optional


class PedestalBase(BaseModel):
    name: str
    location: Optional[str] = None
    ip_address: Optional[str] = None
    data_mode: str = "synthetic"


class PedestalCreate(PedestalBase):
    pass


class PedestalUpdate(BaseModel):
    name: Optional[str] = None
    location: Optional[str] = None
    ip_address: Optional[str] = None
    data_mode: Optional[str] = None


class PedestalResponse(PedestalBase):
    id: int

    model_config = {"from_attributes": True}
