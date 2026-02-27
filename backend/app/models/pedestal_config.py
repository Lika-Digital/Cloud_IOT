from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey
from ..database import Base


class PedestalConfig(Base):
    __tablename__ = "pedestal_configs"

    id            = Column(Integer, primary_key=True, index=True)
    pedestal_id   = Column(Integer, ForeignKey("pedestals.id"), unique=True, nullable=False)

    # Location identifiers
    site_id       = Column(String, nullable=True)
    dock_id       = Column(String, nullable=True)
    berth_ref     = Column(String, nullable=True)
    pedestal_uid  = Column(String, nullable=True)
    pedestal_model = Column(String, nullable=True)   # "16A" | "24A" | "64A"

    # MQTT / OPTA
    mqtt_username  = Column(String, nullable=True)
    mqtt_password  = Column(String, nullable=True)
    opta_client_id = Column(String, nullable=True)

    # Camera
    camera_stream_url = Column(String, nullable=True)
    camera_fqdn       = Column(String, nullable=True)
    camera_username   = Column(String, nullable=True)
    camera_password   = Column(String, nullable=True)

    # Sensor mode
    sensor_config_mode = Column(String, default="auto")   # "auto" | "manual"

    # Discovery results (JSON strings)
    mdns_discovered = Column(String, nullable=True)
    snmp_discovered = Column(String, nullable=True)

    # Health (updated by background tasks)
    opta_connected    = Column(Integer, default=0)
    last_heartbeat    = Column(DateTime, nullable=True)
    camera_reachable  = Column(Integer, default=0)
    last_camera_check = Column(DateTime, nullable=True)

    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PedestalSensor(Base):
    __tablename__ = "pedestal_sensors"

    id           = Column(Integer, primary_key=True, index=True)
    pedestal_id  = Column(Integer, ForeignKey("pedestals.id"), nullable=False)
    sensor_name  = Column(String, nullable=False)
    sensor_type  = Column(String, nullable=False)
    mqtt_topic   = Column(String, nullable=False)
    unit         = Column(String, nullable=True)
    min_alarm    = Column(Float, nullable=True)
    max_alarm    = Column(Float, nullable=True)
    is_active    = Column(Boolean, default=True)
    source       = Column(String, default="manual")   # "manual" | "auto_mqtt"
    created_at   = Column(DateTime, default=datetime.utcnow)
