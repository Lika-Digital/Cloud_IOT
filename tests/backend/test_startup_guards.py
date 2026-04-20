"""
Regression guard for C-4: backend refuses to start in production if JWT_SECRET
is unset or too short. Dev / test environments still allow auto-generated or
short keys for local convenience.
"""
from __future__ import annotations
import importlib
import os
import pytest


def _reload_config(env_overrides: dict[str, str]):
    """Re-import app.config with a monkey-patched environment so the top-level
    validation code runs under the desired APP_ENV / JWT_SECRET."""
    saved = {k: os.environ.get(k) for k in env_overrides}
    try:
        for k, v in env_overrides.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        import app.config as config_module
        return importlib.reload(config_module)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        # Put the module back in a consistent state for downstream tests.
        import app.config as config_module
        importlib.reload(config_module)


def test_production_rejects_missing_jwt_secret():
    """APP_ENV=production + no JWT_SECRET => RuntimeError at import."""
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        _reload_config({"APP_ENV": "production", "JWT_SECRET": ""})


def test_production_rejects_short_jwt_secret():
    """APP_ENV=production + too-short JWT_SECRET => RuntimeError at import."""
    with pytest.raises(RuntimeError, match="at least 32 characters"):
        _reload_config({"APP_ENV": "production", "JWT_SECRET": "too-short"})


def test_dev_tolerates_short_secret():
    """Dev (default) just warns on a short key."""
    mod = _reload_config({"APP_ENV": "dev", "JWT_SECRET": "test-secret-key-for-ci"})
    assert mod.settings.jwt_secret == "test-secret-key-for-ci"
