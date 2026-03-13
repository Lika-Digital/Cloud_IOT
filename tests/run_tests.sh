#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  Cloud_IOT — Automated Test Runner (Linux / macOS / Git Bash on Windows)
#  Usage: bash tests/run_tests.sh [pytest extra args]
#  Called automatically by the pre-commit hook.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$ROOT_DIR"

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║          Cloud_IOT — Automated Test Suite           ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# ── Activate venv ─────────────────────────────────────────────────────────────
VENV_ACTIVATE="backend/.venv/Scripts/activate"   # Git Bash / Windows path
if [ ! -f "$VENV_ACTIVATE" ]; then
    VENV_ACTIVATE="backend/.venv/bin/activate"   # Linux / macOS path
fi
if [ ! -f "$VENV_ACTIVATE" ]; then
    echo "[ERROR] Virtual environment not found."
    echo "        Run: cd backend && python -m venv .venv && pip install -r requirements.txt"
    exit 1
fi
# shellcheck source=/dev/null
source "$VENV_ACTIVATE"

# ── Install test dependencies if missing ─────────────────────────────────────
if ! python -m pytest --version &>/dev/null; then
    echo "[INFO] Installing pytest and test dependencies..."
    pip install pytest pytest-asyncio httpx starlette --quiet
fi

# ── Run backend tests ─────────────────────────────────────────────────────────
echo "[1/1] Running backend tests..."
echo ""
python -m pytest tests/backend/ -v --tb=short --no-header -W ignore::DeprecationWarning "$@"
EXIT_CODE=$?

# ── Cleanup ───────────────────────────────────────────────────────────────────
rm -f tests/test_pedestal.db tests/test_users.db

echo ""
if [ $EXIT_CODE -eq 0 ]; then
    echo "✓ All tests passed."
else
    echo "✗ Tests FAILED — fix errors before committing."
fi

exit $EXIT_CODE
