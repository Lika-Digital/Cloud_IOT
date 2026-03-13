@echo off
REM ─────────────────────────────────────────────────────────────────────────────
REM  Cloud_IOT — Automated Test Runner (Windows)
REM  Usage: tests\run_tests.bat [pytest extra args]
REM  Called automatically by the pre-commit hook.
REM ─────────────────────────────────────────────────────────────────────────────

setlocal EnableDelayedExpansion

echo.
echo ╔══════════════════════════════════════════════════════╗
echo ║          Cloud_IOT — Automated Test Suite           ║
echo ╚══════════════════════════════════════════════════════╝
echo.

REM ── Locate repo root (parent of this script) ─────────────────────────────
set SCRIPT_DIR=%~dp0
set ROOT_DIR=%SCRIPT_DIR%..
cd /d "%ROOT_DIR%"

REM ── Activate Python venv ─────────────────────────────────────────────────
set VENV_ACTIVATE=backend\.venv\Scripts\activate.bat
if not exist "%VENV_ACTIVATE%" (
    echo [ERROR] Virtual environment not found at backend\.venv
    echo         Run: cd backend ^&^& python -m venv .venv ^&^& .venv\Scripts\pip install -r requirements.txt
    exit /b 1
)
call "%VENV_ACTIVATE%"

REM ── Install test dependencies if missing ─────────────────────────────────
python -m pytest --version >nul 2>&1
if errorlevel 1 (
    echo [INFO] Installing pytest and test dependencies...
    pip install pytest pytest-asyncio httpx starlette --quiet
)

REM ── Run backend tests ─────────────────────────────────────────────────────
echo [1/1] Running backend tests...
echo.
python -m pytest tests/backend/ -v --tb=short --no-header -W ignore::DeprecationWarning %* 2>&1
set EXIT_CODE=%ERRORLEVEL%

echo.
if %EXIT_CODE% == 0 (
    echo ✓ All tests passed.
) else (
    echo ✗ Tests FAILED — fix errors before committing.
)

REM ── Clean up test DB files ────────────────────────────────────────────────
if exist "tests\test_pedestal.db" del /f /q "tests\test_pedestal.db"
if exist "tests\test_users.db"    del /f /q "tests\test_users.db"

exit /b %EXIT_CODE%
