from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import Integer, String
from ..database import Base


class SnmpConfig(Base):
    """Persisted SNMP trap receiver configuration (always row id=1)."""
    __tablename__ = "snmp_config"

    id:          Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    enabled:     Mapped[int] = mapped_column(Integer, default=1)
    port:        Mapped[int] = mapped_column(Integer, default=1620)
    community:   Mapped[str] = mapped_column(String, default="public")
    temp_oid:    Mapped[str] = mapped_column(String, default="1.3.6.1.4.1.18248.20.1.2.1.1.2.1")
    pedestal_id: Mapped[int] = mapped_column(Integer, default=1)
