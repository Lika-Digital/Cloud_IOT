import sys
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

SIMULATOR_PATH = Path(__file__).parent.parent.parent.parent / "simulator" / "pedestal_simulator.py"


class SimulatorManager:
    def __init__(self):
        self._process: subprocess.Popen | None = None

    def start(self, pedestal_ids: list[int] | None = None, broker_host: str = "localhost", broker_port: int = 1883):
        if self._process and self._process.poll() is None:
            self.stop()

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
