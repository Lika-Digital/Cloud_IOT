"""Data generators and state managers for the pedestal simulator."""
import random
import math
import time


class TemperatureGenerator:
    """
    Simulates pedestal enclosure temperature.
    Baseline 25°C, rises when sockets are active, drops when idle.
    Range 20–70°C. Alarm threshold is 50°C.
    """

    def __init__(self):
        self._value = random.uniform(22.0, 30.0)

    def next_reading(self, active_socket_count: int = 0) -> dict:
        # Heat up with load, cool down otherwise
        target = 25.0 + active_socket_count * 8.0
        self._value += (target - self._value) * 0.05 + random.gauss(0, 0.5)
        self._value = max(20.0, min(70.0, self._value))
        return {"value": round(self._value, 1)}


class MoistureGenerator:
    """
    Simulates enclosure moisture/humidity.
    Range 60–95%. Rises when water is flowing, falls otherwise.
    Alarm threshold is 90%.
    """

    def __init__(self):
        self._value = random.uniform(62.0, 75.0)

    def next_reading(self, water_active: bool = False) -> dict:
        target = 88.0 if water_active else 65.0
        self._value += (target - self._value) * 0.03 + random.gauss(0, 0.4)
        self._value = max(60.0, min(95.0, self._value))
        return {"value": round(self._value, 1)}


class PowerGenerator:
    """Simulates realistic power consumption for a socket."""

    APPLIANCE_PROFILES = {
        1: {"base": 1800, "variance": 400},   # Shore power
        2: {"base": 7200, "variance": 500},   # EV charger
        3: {"base": 1200, "variance": 300},   # Air conditioner
        4: {"base": 800,  "variance": 200},   # General appliance
    }

    def __init__(self, socket_id: int):
        self.socket_id = socket_id
        self.profile = self.APPLIANCE_PROFILES.get(socket_id, self.APPLIANCE_PROFILES[4])
        self._kwh_total = round(random.uniform(0, 50), 3)
        self._last_time = time.time()
        self._phase = random.uniform(0, 2 * math.pi)

    def next_reading(self) -> dict:
        now = time.time()
        dt = now - self._last_time
        self._last_time = now

        base = self.profile["base"]
        variance = self.profile["variance"]
        watts = max(0.0, base + variance * math.sin(now / 30 + self._phase) + random.gauss(0, variance * 0.1))

        self._kwh_total += (watts * dt) / 3_600_000
        return {"watts": round(watts, 2), "kwh_total": round(self._kwh_total, 6)}


class WaterGenerator:
    """Simulates water flow during an active water session."""

    def __init__(self):
        self._total_liters = round(random.uniform(0, 200), 2)
        self._last_time = time.time()

    def next_reading(self, flowing: bool) -> dict:
        now = time.time()
        dt = now - self._last_time
        self._last_time = now

        if flowing:
            lpm = max(5.0, min(30.0, random.gauss(18, 3)))
        else:
            lpm = 0.0

        self._total_liters = round(self._total_liters + (lpm / 60) * dt, 4)
        return {"lpm": round(lpm, 2), "total_liters": self._total_liters}


class SocketStateManager:
    """
    State machine for one electricity socket.

    Flow:
        IDLE → (random plug-in) → PENDING  [sends "connected"]
        PENDING → (allow received) → ACTIVE [sends power readings for 2-10 min]
        PENDING → (deny/timeout 30s) → IDLE [sends "disconnected"]
        ACTIVE → (random 2-10 min elapsed) → IDLE [sends "disconnected"]
        ACTIVE → (stop received) → IDLE     [sends "disconnected"]
    """

    IDLE = "idle"
    PENDING = "pending"
    ACTIVE = "active"

    # Each socket has a slightly different connect probability to avoid
    # all sockets connecting at the same time
    _BASE_CONNECT_PROB = 0.004

    def __init__(self, socket_id: int):
        self.socket_id = socket_id
        self.state = self.IDLE
        self._state_entered_at = 0.0
        self._session_duration_s = 0.0
        self._connect_prob = self._BASE_CONNECT_PROB + socket_id * 0.001

    def tick(self) -> str | None:
        """
        Called every ~0.5s. Returns 'connected', 'disconnected', or None.
        """
        now = time.time()

        if self.state == self.IDLE:
            if random.random() < self._connect_prob:
                self.state = self.PENDING
                self._state_entered_at = now
                return "connected"

        elif self.state == self.PENDING:
            # Auto-cancel if no response within 30 seconds
            if now - self._state_entered_at > 30:
                self.state = self.IDLE
                return "disconnected"

        elif self.state == self.ACTIVE:
            if now - self._state_entered_at > self._session_duration_s:
                self.state = self.IDLE
                return "disconnected"

        return None

    def on_control(self, command: str):
        """Handle control message from backend."""
        if command == "allow" and self.state == self.PENDING:
            self.state = self.ACTIVE
            self._state_entered_at = time.time()
            self._session_duration_s = random.uniform(120, 600)  # 2–10 minutes
        elif command in ("deny", "stop") and self.state != self.IDLE:
            self.state = self.IDLE

    @property
    def is_active(self) -> bool:
        return self.state == self.ACTIVE


class WaterStateManager:
    """
    State machine for the water meter — mirrors SocketStateManager logic.

    Flow:
        IDLE → (random flow start) → PENDING  [sends lpm > 0]
        PENDING → (allow received) → ACTIVE   [sends flow readings for 2-10 min]
        PENDING → (deny/timeout 30s) → IDLE   [sends lpm = 0]
        ACTIVE → (2-10 min elapsed) → IDLE    [sends lpm = 0]
        ACTIVE → (stop received) → IDLE       [sends lpm = 0]
    """

    IDLE = "idle"
    PENDING = "pending"
    ACTIVE = "active"

    def __init__(self):
        self.state = self.IDLE
        self._state_entered_at = 0.0
        self._session_duration_s = 0.0
        self._connect_prob = 0.002

    def tick(self) -> str | None:
        """Returns 'start', 'stop', or None."""
        now = time.time()

        if self.state == self.IDLE:
            if random.random() < self._connect_prob:
                self.state = self.PENDING
                self._state_entered_at = now
                return "start"

        elif self.state == self.PENDING:
            if now - self._state_entered_at > 30:
                self.state = self.IDLE
                return "stop"

        elif self.state == self.ACTIVE:
            if now - self._state_entered_at > self._session_duration_s:
                self.state = self.IDLE
                return "stop"

        return None

    def on_control(self, command: str):
        if command == "allow" and self.state == self.PENDING:
            self.state = self.ACTIVE
            self._state_entered_at = time.time()
            self._session_duration_s = random.uniform(120, 600)
        elif command in ("deny", "stop") and self.state != self.IDLE:
            self.state = self.IDLE

    @property
    def is_active(self) -> bool:
        return self.state == self.ACTIVE

    @property
    def is_flowing(self) -> bool:
        return self.state in (self.PENDING, self.ACTIVE)
