"""Starts and stops the pedestal simulator subprocess.

**THE SIMULATOR IS NOT IN THIS REPOSITORY.** It was deleted on 2026-03-15 by `be0df4f`
("fix(nuc-image): remove simulator…"), which removed `simulator/pedestal_simulator.py` (261
lines) and `simulator/generators.py` (219 lines). The stated reason was "not needed on NUC" —
but it was removed from the repo entirely rather than excluded from the NUC image, so nothing
has been able to start a simulator since.

This module was left pointing at the deleted path. `Popen` on a missing file raises
`FileNotFoundError`, which was caught and logged — so "Start Simulator" in the dashboard
**failed silently into the error log for six months** and told the operator nothing. That is
worse than a missing feature: a button that does nothing and explains nothing sends someone
looking for a fault that is not there.

`simulator_available()` and the explicit not-installed reporting below exist so the absence is
stated rather than discovered. A rewrite against the current MQTT contract (the `opta/*` topic
family, per-valve water, the six-tag model) is planned — see `docs/engineering_notes.md`.
"""
import logging
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

SIMULATOR_PATH = Path(__file__).parent.parent.parent.parent / "simulator" / "pedestal_simulator.py"

# Why the operator is told "not installed" rather than "failed to start": those are different
# problems with different answers, and conflating them is what made this invisible.
NOT_INSTALLED_MESSAGE = (
    "The simulator is not installed. It was removed from the repository in March 2026 "
    "(commit be0df4f) and has not been replaced, so synthetic mode cannot generate data. "
    "Use a real pedestal, or ask for the simulator to be rebuilt."
)


def simulator_available() -> bool:
    """Whether a simulator exists to start. Checked, never assumed."""
    return SIMULATOR_PATH.is_file()


class SimulatorManager:
    def __init__(self):
        self._process: subprocess.Popen | None = None
        # Set when a start was attempted and could not proceed, so callers can report the
        # reason instead of only "not running".
        self.last_error: str | None = None

    def start(self, pedestal_ids: list[int] | None = None, broker_host: str = "localhost", broker_port: int = 1883):
        if self._process and self._process.poll() is None:
            self.stop()

        if not simulator_available():
            # Stated once, loudly, and remembered — not swallowed by the generic except below.
            self.last_error = NOT_INSTALLED_MESSAGE
            logger.error("Simulator not installed: %s does not exist. %s",
                         SIMULATOR_PATH, NOT_INSTALLED_MESSAGE)
            try:
                from .error_log_service import log_error
                log_error("system", "simulator_manager", NOT_INSTALLED_MESSAGE)
            except Exception:
                pass
            self._process = None
            return

        self.last_error = None
        ids = pedestal_ids or [1]
        ids_str = ",".join(str(i) for i in ids)

        cmd = [
            sys.executable,
            str(SIMULATOR_PATH),
            "--pedestal-ids", ids_str,
            "--broker-host", broker_host,
            "--broker-port", str(broker_port),
        ]
        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            logger.info(f"Simulator started for pedestals [{ids_str}] (PID={self._process.pid})")
        except Exception as e:
            logger.error(f"Failed to start simulator: {e}")
            try:
                from .error_log_service import log_error
                log_error("system", "simulator_manager", f"Failed to start simulator: {e}")
            except Exception:
                pass
            self._process = None

    def stop(self):
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
            except Exception as e:
                logger.warning(f"Error stopping simulator: {e}")
            finally:
                self._process = None
            logger.info("Simulator stopped")

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None


simulator_manager = SimulatorManager()
