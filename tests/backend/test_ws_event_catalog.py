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
    orphans = backend_events - frontend_cases - INTERNAL_EVENTS
    assert not orphans, (
        f"Backend broadcasts these events but no frontend handler and not marked internal: {orphans}. "
        f"Either add a `case '<name>':` in frontend/src/hooks/useWebSocket.ts "
        f"or add the event to INTERNAL_EVENTS in this test."
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
