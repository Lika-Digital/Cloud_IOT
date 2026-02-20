import sys
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

SIMULATOR_PATH = Path(__file__).parent.parent.parent.parent / "simulator" / "pedestal_simulator.py"


class SimulatorManager:
    def __init__(self):
        self._process: subprocess.Popen | None = None

    def start(self, pedestal_id: int = 1, broker_host: str = "localhost", broker_port: int = 1883):
        if self._process and self._process.poll() is None:
            logger.info("Simulator already running")
            return

        cmd = [
            sys.executable,
            str(SIMULATOR_PATH),
            "--pedestal-id", str(pedestal_id),
            "--broker-host", broker_host,
            "--broker-port", str(broker_port),
        ]
        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            logger.info(f"Simulator started (PID={self._process.pid})")
        except Exception as e:
            logger.error(f"Failed to start simulator: {e}")
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
