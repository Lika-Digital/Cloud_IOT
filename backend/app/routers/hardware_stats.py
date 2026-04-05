"""
hardware_stats.py — GET /api/system/hardware-stats

Single endpoint that collects all NUC hardware parameters on demand,
evaluates alarm thresholds, applies downgrade actions for new critical alarms,
and pushes a 'hardware_alarm' WebSocket event to all connected clients.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from ..auth.dependencies import require_admin
from ..auth.models import User
from ..services import hardware_monitor as hw
from ..services.error_log_service import log_warning
from ..services.websocket_manager import ws_manager

router = APIRouter(prefix="/api/system", tags=["hardware"])


@router.get("/hardware-stats")
async def get_hardware_stats(_: User = Depends(require_admin)):
    """
    Collect all NUC hardware parameters in one call (< 500ms target).

    Returns hardware stats, active alarms, and the automatic-action log.
    For newly-triggered Alarm 2 (critical) events:
      - Applies the appropriate downgrade action (nice/gc/suspend/log-only)
      - Pushes a 'hardware_alarm' WebSocket event to all connected dashboards
      - Logs a warning to the error_log table
    """
    stats  = hw.get_hardware_stats()
    alarms = hw.check_alarms(stats)

    # Evaluate new critical alarms — deduplicated inside evaluate_and_act()
    new_actions = hw.evaluate_and_act(alarms)

    # For each newly-triggered critical alarm: push WS + log
    for action in new_actions:
        alarm = next((a for a in alarms if a["param"] == action["param"]), None)
        if alarm:
            await ws_manager.broadcast({
                "type": "hardware_alarm",
                "data": {
                    "alarm_level": alarm["level"],
                    "param":       alarm["param"],
                    "label":       alarm["label"],
                    "value":       alarm["value"],
                    "threshold":   alarm["threshold"],
                    "unit":        alarm["unit"],
                    "timestamp":   datetime.now(timezone.utc).isoformat(),
                },
            })
            log_warning(
                "hw",
                "hardware_monitor",
                f"Critical alarm: {alarm['label']} = {alarm['value']}{alarm['unit']} "
                f"(threshold {alarm['threshold']}{alarm['unit']})",
                details=action["action"],
            )

    return {
        **stats,
        "alarms":     alarms,
        "action_log": hw.get_action_log(),
    }
