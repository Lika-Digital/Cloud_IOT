"""Realistic data generators for the pedestal simulator."""
import random
import math
import time


class PowerGenerator:
    """Simulates realistic power consumption patterns."""

    APPLIANCE_PROFILES = {
        "shore_power": {"base": 1800, "variance": 400, "surge": 3500},
        "ev_charger": {"base": 7200, "variance": 500, "surge": 7700},
        "air_conditioner": {"base": 1200, "variance": 300, "surge": 2000},
        "general": {"base": 800, "variance": 200, "surge": 1500},
    }

    def __init__(self, socket_id: int):
        self.socket_id = socket_id
        profile_name = list(self.APPLIANCE_PROFILES.keys())[socket_id % len(self.APPLIANCE_PROFILES)]
        self.profile = self.APPLIANCE_PROFILES[profile_name]
        self._kwh_total = round(random.uniform(0, 100), 3)
        self._last_time = time.time()
        self._phase = random.uniform(0, 2 * math.pi)

    def next_reading(self) -> dict:
        now = time.time()
        dt = now - self._last_time
        self._last_time = now

        # Sinusoidal variation + noise
        base = self.profile["base"]
        variance = self.profile["variance"]
        sine = variance * math.sin(now / 30 + self._phase)
        noise = random.gauss(0, variance * 0.1)
        watts = max(0.0, base + sine + noise)

        # Occasional surge
        if random.random() < 0.02:
            watts = self.profile["surge"] * random.uniform(0.8, 1.1)

        # Accumulate kWh
        self._kwh_total += (watts * dt) / 3_600_000
        self._kwh_total = round(self._kwh_total, 6)

        return {"watts": round(watts, 2), "kwh_total": self._kwh_total}


class WaterGenerator:
    """Simulates realistic water flow patterns."""

    def __init__(self):
        self._total_liters = round(random.uniform(0, 500), 2)
        self._last_time = time.time()
        self._flow_active = False
        self._flow_start = 0.0

    def next_reading(self) -> dict:
        now = time.time()
        dt = now - self._last_time
        self._last_time = now

        # Realistic flow: bursts of usage
        if not self._flow_active:
            if random.random() < 0.05:
                self._flow_active = True
                self._flow_start = now
        else:
            # Flow lasts 10-120 seconds
            duration = now - self._flow_start
            if duration > random.uniform(10, 120):
                self._flow_active = False

        if self._flow_active:
            # Typical hose flow 10-25 liters/minute
            lpm = random.gauss(18, 3)
            lpm = max(5.0, min(30.0, lpm))
        else:
            lpm = 0.0

        liters_now = (lpm / 60) * dt
        self._total_liters = round(self._total_liters + liters_now, 4)

        return {"lpm": round(lpm, 2), "total_liters": self._total_liters}


class SocketStateManager:
    """Manages the connect/disconnect lifecycle of a socket."""

    def __init__(self, socket_id: int, connect_prob: float = 0.003):
        self.socket_id = socket_id
        self.connected = False
        self._connect_prob = connect_prob
        self._disconnect_prob = 0.001
        self._session_duration = 0
        self._max_duration = random.randint(30, 300)  # seconds

    def tick(self) -> str | None:
        """Returns 'connected', 'disconnected', or None if no state change."""
        if not self.connected:
            if random.random() < self._connect_prob:
                self.connected = True
                self._session_duration = 0
                self._max_duration = random.randint(60, 600)
                return "connected"
        else:
            self._session_duration += 1
            if self._session_duration >= self._max_duration or random.random() < self._disconnect_prob:
                self.connected = False
                return "disconnected"
        return None
