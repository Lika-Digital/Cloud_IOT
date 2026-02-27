from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime
from ..database import Base


class ExternalApiConfig(Base):
    __tablename__ = "external_api_config"

    id                   = Column(Integer, primary_key=True)   # always 1
    api_key              = Column(String, nullable=True)        # JWT
    allowed_endpoints    = Column(String, default="[]")         # JSON [{id, mode}]
    webhook_url          = Column(String, nullable=True)
    allowed_events       = Column(String, default="[]")         # JSON [event_id, ...]
    active               = Column(Integer, default=0)
    verified             = Column(Integer, default=0)
    last_verified_at     = Column(DateTime, nullable=True)
    verification_results = Column(String, nullable=True)        # JSON
    created_at           = Column(DateTime, default=datetime.utcnow)
    updated_at           = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
