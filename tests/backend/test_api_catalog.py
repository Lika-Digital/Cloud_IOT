"""
Regression guard: every ENDPOINT_CATALOG entry must correspond to a real route.

This test AST-walks every backend router and collects `@router.<method>("<path>")`
decorators. It then checks the ENDPOINT_CATALOG in api_catalog.py against that
set so a rename / delete on the router side cannot silently break the external
API gateway for integrators.
"""
from __future__ import annotations
import ast
import re
from pathlib import Path


ROOT         = Path(__file__).resolve().parents[2]
ROUTERS_DIR  = ROOT / "backend" / "app" / "routers"
CATALOG_PY   = ROOT / "backend" / "app" / "services" / "api_catalog.py"


def _router_prefix(module_source: str) -> str:
    """Extract APIRouter(prefix='...') from a router module. Default '' if absent."""
    m = re.search(r"APIRouter\([^)]*prefix\s*=\s*['\"]([^'\"]+)['\"]", module_source)
    return m.group(1) if m else ""


def _scan_router_paths() -> set[tuple[str, str]]:
    """Return the set of (METHOD, full_path) declared by every @router decorator."""
    routes: set[tuple[str, str]] = set()
    for py in ROUTERS_DIR.rglob("*.py"):
        if py.name == "__init__.py":
            continue
        src = py.read_text(encoding="utf-8")
        prefix = _router_prefix(src)
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not (isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef)):
                continue
            for deco in node.decorator_list:
                # @router.get("/path") / @router.post("/path") / etc.
                if (
                    isinstance(deco, ast.Call)
                    and isinstance(deco.func, ast.Attribute)
                    and isinstance(deco.func.value, ast.Name)
                    and deco.func.value.id == "router"
                    and deco.func.attr.upper() in {"GET", "POST", "PUT", "PATCH", "DELETE"}
                    and deco.args
                    and isinstance(deco.args[0], ast.Constant)
                    and isinstance(deco.args[0].value, str)
                ):
                    method = deco.func.attr.upper()
                    path_suffix = deco.args[0].value
                    full = (prefix + path_suffix) if not path_suffix.startswith(prefix) else path_suffix
                    routes.add((method, full))
    return routes


def _scan_catalog() -> list[dict]:
    """Read ENDPOINT_CATALOG entries without importing (keeps test lightweight)."""
    tree = ast.parse(CATALOG_PY.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "ENDPOINT_CATALOG" for t in node.targets
        ):
            out: list[dict] = []
            for item in node.value.elts:  # type: ignore[attr-defined]
                if not isinstance(item, ast.Dict):
                    continue
                entry: dict = {}
                for k, v in zip(item.keys, item.values):
                    if isinstance(k, ast.Constant) and isinstance(v, ast.Constant):
                        entry[k.value] = v.value
                out.append(entry)
            return out
    return []


def _normalise(path: str) -> str:
    """
    Router paths use FastAPI-style placeholders `{id}` and `{pedestal_id}`.
    The catalog uses the same. Replace any placeholder token with '{X}'
    so catalog and router paths compare on structure, not var name.
    """
    return re.sub(r"\{[^}]+\}", "{X}", path)


def test_catalog_only_lists_real_routes() -> None:
    """Every ENDPOINT_CATALOG entry must exist as a declared @router route."""
    catalog = _scan_catalog()
    routes = _scan_router_paths()

    route_set = {(m, _normalise(p)) for (m, p) in routes}

    # Ext gateway routes aren't in app/routers (they're served dynamically).
    EXT_GATEWAY_PREFIX = "/api/ext/"
    phantom: list[str] = []
    for entry in catalog:
        key = (entry["method"], _normalise(entry["path"]))
        if entry["path"].startswith(EXT_GATEWAY_PREFIX):
            continue  # proxied or served by ext_pedestal_endpoints — covered by its own tests
        if key not in route_set:
            phantom.append(f"{entry['method']} {entry['path']} (id={entry['id']})")

    assert not phantom, (
        "api_catalog.ENDPOINT_CATALOG advertises endpoints that do not exist:\n  "
        + "\n  ".join(phantom)
        + "\nEither add the route, or remove the catalog entry."
    )
