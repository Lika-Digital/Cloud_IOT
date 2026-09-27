"""
Regression guard: the set of WebSocket event names broadcast by the backend
must stay in sync with the set of `case '...'` handlers in the React client
AND with the External API EVENT_CATALOG.

This test AST-walks the backend source and regex-scans the frontend useWebSocket
hook so that if anyone adds a new broadcast without wiring the client (or vice
versa), the build fails immediately.

Events intentionally internal (fired for audit logs, never consumed by the UI
or external integrators) must be added to INTERNAL_EVENTS below so they are
not flagged as orphans.
"""
from __future__ import annotations
import ast
import re
from pathlib import Path


ROOT         = Path(__file__).resolve().parents[2]
BACKEND_DIR  = ROOT / "backend" / "app"
FRONTEND_WS  = ROOT / "frontend" / "src" / "hooks" / "useWebSocket.ts"
CATALOG_PY   = BACKEND_DIR / "services" / "api_catalog.py"

# Events that are broadcast but intentionally NOT consumed by the dashboard
# (logged, forwarded to external webhooks, or used by a different surface).
INTERNAL_EVENTS = {
    "error_logged",          # admin error-log panel uses REST, not WS
    "chat_message",          # chat page has its own subscription
    "direct_cmd_sent",       # audit trail only
    "training_storage_alarm",# storage monitor — backend-only
    "pedestal_reset_sent",   # logged via REST
    "invoice_created",       # billing page fetches via REST
    "diagnostics_result",    # diagnostics panel fetches via REST
    # v3.6 — mobile-only events. Delivered via broadcast_to_session() to
    # the customer's mobile WebSocket subscription, never to the operator
    # dashboard, so there is no case in useWebSocket.ts by design.
    "session_telemetry",
    "session_ended",
}

# v3.42 — Guard events. These are NOT internal: UI v2 will consume every one of them.
#
# Step 6 (the guard admin screen) was cancelled and merged into UI v2, so step 5 ships the
# complete contract while the frontend handlers arrive later. Marking these INTERNAL would be
# a lie that never gets corrected — the drift guard would stay green even after UI v2 shipped
# without handlers. This separate list records the real state: declared, awaiting a consumer.
#
# test_pending_frontend_events_are_not_yet_handled() below FAILS once a handler appears, so
# the entry has to be deleted then. That is what stops this list becoming a graveyard.
PENDING_FRONTEND_EVENTS = {
    "guard_state_changed",
    "guard_health",
    "guard_alarm",
    "guard_recording_ready",
    "guard_retention_state_changed",
}


def _scan_backend_events() -> set[str]:
    """Return every string literal used as `"event": "<name>"` in ws broadcasts."""
    events: set[str] = set()
    for py in BACKEND_DIR.rglob("*.py"):
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            for key, value in zip(node.keys, node.values):
                if (
                    isinstance(key, ast.Constant) and key.value == "event"
                    and isinstance(value, ast.Constant) and isinstance(value.value, str)
                ):
                    events.add(value.value)
    # v3.24 — alarm_service emits via the `_broadcast(alarm, "<event>")` helper,
    # so these event names are not literal `"event":` dict values the AST scan
    # above can see. They are genuinely broadcast (alarm_service._broadcast).
    events |= {"alarm_triggered", "alarm_acknowledged", "alarm_resolved"}
    return events


def _scan_frontend_cases() -> set[str]:
    text = FRONTEND_WS.read_text(encoding="utf-8")
    return set(re.findall(r"case\s+'([^']+)'\s*:", text))


def _scan_catalog_events() -> set[str]:
    """Read EVENT_CATALOG entries without importing (test runs without app setup)."""
    tree = ast.parse(CATALOG_PY.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "EVENT_CATALOG" for t in node.targets
        ):
            ids: set[str] = set()
            for item in node.value.elts:  # type: ignore[attr-defined]
                if isinstance(item, ast.Dict):
                    for k, v in zip(item.keys, item.values):
                        if (
                            isinstance(k, ast.Constant) and k.value == "id"
                            and isinstance(v, ast.Constant)
                        ):
                            ids.add(v.value)
            return ids
    return set()


def test_every_backend_event_is_handled_or_internal() -> None:
    """A backend broadcast must either match a frontend case OR be in INTERNAL_EVENTS."""
    backend_events = _scan_backend_events()
    frontend_cases = _scan_frontend_cases()
    orphans = backend_events - frontend_cases - INTERNAL_EVENTS - PENDING_FRONTEND_EVENTS
    assert not orphans, (
        f"Backend broadcasts these events but no frontend handler and not marked internal: {orphans}. "
        f"Either add a `case '<name>':` in frontend/src/hooks/useWebSocket.ts "
        f"or add it to INTERNAL_EVENTS (never consumed by the UI) or "
        f"PENDING_FRONTEND_EVENTS (a consumer is coming) in this test."
    )


def test_every_frontend_case_is_broadcast_by_backend() -> None:
    """Every frontend `case '...'` must correspond to a real backend broadcast."""
    backend_events = _scan_backend_events()
    frontend_cases = _scan_frontend_cases()
    dead_cases = frontend_cases - backend_events
    assert not dead_cases, (
        f"Frontend handles these events but backend never broadcasts them: {dead_cases}. "
        f"Either wire the backend broadcast or remove the `case` from useWebSocket.ts."
    )


def test_external_catalog_only_contains_broadcast_events() -> None:
    """EVENT_CATALOG advertises events — each must actually exist in the backend."""
    backend_events = _scan_backend_events()
    catalog_events = _scan_catalog_events()
    phantom = catalog_events - backend_events
    assert not phantom, (
        f"api_catalog.EVENT_CATALOG advertises events that backend never broadcasts: {phantom}. "
        f"Remove from catalog or add a `ws_manager.broadcast({{'event': '<name>', ...}})` call."
    )


def test_pending_frontend_events_are_not_yet_handled() -> None:
    """PENDING_FRONTEND_EVENTS must stay honest.

    Once UI v2 adds a `case 'guard_alarm':` the event is no longer pending, and leaving it
    listed would quietly exempt it from the drift guard forever. So this fails the moment a
    handler exists, forcing the entry to be removed — which is the whole reason guard events
    are not lumped into INTERNAL_EVENTS.
    """
    frontend_cases = _scan_frontend_cases()
    now_handled = PENDING_FRONTEND_EVENTS & frontend_cases
    assert not now_handled, (
        f"These events now HAVE frontend handlers: {sorted(now_handled)}. Remove them from "
        f"PENDING_FRONTEND_EVENTS so the drift guard covers them again — leaving them listed "
        f"exempts them permanently."
    )
