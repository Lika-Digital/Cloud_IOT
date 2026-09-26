"""
Guard shared modules must stay importable from the staging venv (step 2, v3.42)
==============================================================================

`app/guard/pipeline.py` and `app/guard/alarm_rule.py` are shared by three consumers: the
backend, the `guard_worker` service, and `scripts/guard_detect_probe.py`. The probe runs
from `$HOME/guard-staging/venv`, which deliberately contains only **openvino + numpy +
Pillow** — no FastAPI, no SQLAlchemy, no pydantic.

That isolation is what makes the whole measurement flow possible without touching the
production venv (proved in `docs/guard_stage_a5_addendum.md` §A1: `app/__init__.py` and
`app/services/__init__.py` are both 0 bytes and the detector imports only stdlib at module
level). It is also **fragile in a way that is invisible until someone runs the probe on the
NUC**: one convenience import of `..database` or `fastapi` inside a shared module breaks it,
and every backend test would still pass.

So it is asserted here, statically, in a way that does not depend on what happens to be
installed in the test environment.

  TC-GIS-01  the shared modules import no forbidden top-level module
  TC-GIS-02  ...nor via `from X import ...`
  TC-GIS-03  the shared modules do not import from the wider app package
  TC-GIS-04  guard_worker.capture is stdlib-only (it must run before numpy is needed)
  TC-GIS-05  heavy imports in the shared modules are function-local, not module-level
  TC-GIS-06  the modules really do import with only numpy+PIL available
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

SHARED_MODULES = [
    REPO / "backend" / "app" / "guard" / "pipeline.py",
    REPO / "backend" / "app" / "guard" / "alarm_rule.py",
]
WORKER_CAPTURE = REPO / "guard_worker" / "capture.py"

# Absent from the staging venv. A top-level import of any of these breaks the probe.
FORBIDDEN = {
    "fastapi", "starlette", "sqlalchemy", "pydantic", "pydantic_settings",
    "uvicorn", "httpx", "paho", "jwt", "reportlab", "slowapi", "qrcode",
    "sklearn", "scikit_learn", "cv2", "torch", "ultralytics",
}
# Allowed at module level in the shared modules: stdlib only. numpy/PIL/openvino are
# permitted ONLY inside functions (TC-GIS-05), so import cost stays off the module path.
HEAVY_BUT_ALLOWED_IN_FUNCTIONS = {"numpy", "PIL", "openvino"}


def _module_level_imports(path: Path) -> set[str]:
    """Top-level import names only — imports nested inside functions/classes excluded."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in tree.body:                      # tree.body == module level only
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                names.add("." * node.level + (node.module or ""))
            elif node.module:
                names.add(node.module.split(".")[0])
    return names


def _all_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


@pytest.mark.parametrize("path", SHARED_MODULES, ids=lambda p: p.name)
def test_tc_gis_01_02_no_forbidden_imports_anywhere(path):
    """Forbidden even inside functions: a lazy `import sqlalchemy` would still fail on the
    NUC the moment that code path ran, which is worse than failing at import time."""
    offenders = _all_imports(path) & FORBIDDEN
    assert not offenders, (
        f"{path.name} imports {sorted(offenders)}, which is NOT installed in the staging "
        f"venv ($HOME/guard-staging/venv has only openvino + numpy + Pillow). This breaks "
        f"scripts/guard_detect_probe.py on the NUC while every backend test still passes. "
        f"If the backend needs this, put it in service.py or router.py, not in a module "
        f"the worker and probe share."
    )


@pytest.mark.parametrize("path", SHARED_MODULES, ids=lambda p: p.name)
def test_tc_gis_03_no_wider_app_imports_at_module_level(path):
    """The shared modules must not drag in the rest of the backend.

    `from ..database import ...` or `from ..config import settings` would pull SQLAlchemy
    and pydantic-settings transitively — the failure would come from a module the author
    never mentioned, which is exactly the kind of breakage that is hard to diagnose in the
    field.
    """
    top = _module_level_imports(path)
    relative = {n for n in top if n.startswith(".")}
    assert not relative, (
        f"{path.name} has module-level relative imports {sorted(relative)}. Shared guard "
        f"modules must not import from the wider app package: it pulls SQLAlchemy and "
        f"pydantic in transitively and breaks the staging venv. Inject what you need as a "
        f"parameter instead — that is why process_frame() takes the detector as an argument."
    )


def test_tc_gis_04_worker_capture_is_stdlib_only():
    """`guard_worker/capture.py` runs ffmpeg and hands out JPEG bytes. It must not need
    numpy or PIL at all — capture has to work before anything is decoded, and keeping it
    stdlib-only means a detection dependency problem cannot stop the segment ring (and the
    evidence it records) from working."""
    imports = _all_imports(WORKER_CAPTURE)
    not_allowed = (imports & FORBIDDEN) | (imports & HEAVY_BUT_ALLOWED_IN_FUNCTIONS)
    assert not not_allowed, (
        f"guard_worker/capture.py imports {sorted(not_allowed)}. Capture is deliberately "
        f"stdlib-only so the segment ring keeps recording evidence even if the detection "
        f"stack has a problem."
    )


@pytest.mark.parametrize("path", SHARED_MODULES, ids=lambda p: p.name)
def test_tc_gis_05_heavy_imports_are_function_local(path):
    """numpy/PIL/openvino must be imported inside functions, not at module level.

    Keeps `import app.guard.pipeline` cheap and, more importantly, keeps it working on the
    32-bit dev box where some of these have no wheels — which is how the whole codebase
    already treats them (`berth_analyzer`, `yolo_openvino`).
    """
    at_module_level = _module_level_imports(path) & HEAVY_BUT_ALLOWED_IN_FUNCTIONS
    assert not at_module_level, (
        f"{path.name} imports {sorted(at_module_level)} at module level. Move it inside the "
        f"function that needs it, matching the existing convention in berth_analyzer.py and "
        f"yolo_openvino.py."
    )


def test_tc_gis_06_modules_import_with_only_numpy_and_pil(monkeypatch):
    """Belt to the static braces: actually import them with the forbidden modules blocked.

    Static analysis cannot see a transitive import, so this simulates the staging venv by
    making the forbidden names unimportable and then importing the shared modules fresh.
    """
    import builtins

    real_import = builtins.__import__

    def guarded(name, *args, **kwargs):
        root = name.split(".")[0]
        if root in FORBIDDEN:
            raise ImportError(
                f"{root} is not available in the staging venv (simulated by TC-GIS-06)"
            )
        return real_import(name, *args, **kwargs)

    for mod in ("app.guard.pipeline", "app.guard.alarm_rule", "app.guard"):
        sys.modules.pop(mod, None)

    monkeypatch.setattr(builtins, "__import__", guarded)
    try:
        import importlib

        pipeline = importlib.import_module("app.guard.pipeline")
        alarm_rule = importlib.import_module("app.guard.alarm_rule")
    finally:
        monkeypatch.undo()
        for mod in ("app.guard.pipeline", "app.guard.alarm_rule", "app.guard"):
            sys.modules.pop(mod, None)

    # And they are actually usable, not just importable.
    assert pipeline.classify_band(0.9, pipeline.PipelineConfig()) == pipeline.BAND_ALARM
    assert alarm_rule.DEFAULT_WINDOW_SECONDS == 4.0
