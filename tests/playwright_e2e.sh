#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  Cloud_IOT — Playwright E2E Test Runner
#
#  Runs all Playwright specs in frontend/e2e/ against a headless Chromium.
#  Vite dev server is started/reused automatically by playwright.config.ts.
#
#  Usage: bash tests/playwright_e2e.sh
#  Called automatically by the pre-push hook.
# ─────────────────────────────────────────────────────────────────────────────
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$ROOT_DIR"

YELLOW='\033[1;33m'; RED='\033[0;31m'; GREEN='\033[0;32m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

LOG_DIR="${SCRIPT_DIR}/logs"
mkdir -p "$LOG_DIR"

echo ""
echo -e "${CYAN}${BOLD}[E2E] Playwright end-to-end tests${NC}"
echo ""

# ─── WHY THERE IS NO LONGER A SILENT exit 0 HERE ─────────────────────────────
#
# Three branches used to `exit 0` when they could not run: no node, no Playwright,
# and no backend on :8000. All three reported SUCCESS for having verified nothing, and
# on the 2026-09-30 push the last one did exactly that — the stage printed a skip and the
# gate went green.
#
# The backend check was also simply WRONG. Every spec in frontend/e2e/ mocks its API with
# Playwright's `page.route`, and playwright.config.ts starts Vite itself. None of them has
# ever needed a live API, so the check skipped tests that would have passed.
#
# Now: a missing TOOL is a hard failure (fix your environment), and the backend is not
# consulted at all. E2E_REQUIRED=0 is available for a deliberate local skip and still
# prints what was not checked.

E2E_REQUIRED="${E2E_REQUIRED:-1}"

not_run() {
    echo -e "${YELLOW}[!] E2E NOT RUN: $1${NC}"
    if [ "$E2E_REQUIRED" = "1" ]; then
        echo -e "${RED}    This is a FAILURE TO REPORT, not a pass. Nothing was verified.${NC}"
        echo    "    Set E2E_REQUIRED=0 to skip deliberately."
        exit 1
    fi
    echo    "    E2E_REQUIRED=0 — skipping deliberately. NOTHING WAS VERIFIED."
    exit 0
}

# ── Node ─────────────────────────────────────────────────────────────────────
if ! command -v node &>/dev/null; then
    not_run "Node.js not found. Install Node, or set E2E_REQUIRED=0."
fi

# ── Playwright ───────────────────────────────────────────────────────────────
if [ ! -d "frontend/node_modules/@playwright" ]; then
    not_run "Playwright is not installed. Run: cd frontend && npm install"
fi

# NOTE: no backend check. The specs mock their own API and Vite is started by
# playwright.config.ts. A live backend is neither needed nor consulted.
# ── Run Playwright ─────────────────────────────────────────────────────────────
cd frontend
# playwright.config.ts already configures both list + json reporters
npx playwright test 2>&1 | tee "../tests/logs/playwright_stdout.log"
PW_EXIT=${PIPESTATUS[0]}
cd "$ROOT_DIR"

echo ""
if [ $PW_EXIT -eq 0 ]; then
    echo -e "${GREEN}[✔] Playwright E2E passed${NC}"
else
    # Parse JSON for a summary
    SUMMARY=$(python - "${LOG_DIR}/playwright_last.json" << 'PYEOF'
import sys, json, os
path = sys.argv[1]
if not os.path.exists(path):
    print("PARSE_ERROR=no JSON output found")
    sys.exit(0)
try:
    with open(path) as f:
        data = json.load(f)
    total  = data.get("stats", {}).get("expected", 0)
    passed = data.get("stats", {}).get("passed", 0)
    failed = data.get("stats", {}).get("failed", 0)
    skipped= data.get("stats", {}).get("skipped", 0)
    print(f"TOTAL={total} PASSED={passed} FAILED={failed} SKIPPED={skipped}")
    for suite in data.get("suites", []):
        for spec in suite.get("specs", []):
            for test in spec.get("tests", []):
                if test.get("status") == "failed":
                    title = spec.get("title","?")
                    print(f"FAIL={title}")
except Exception as e:
    print(f"PARSE_ERROR={e}")
PYEOF
)
    echo -e "${RED}[✘] Playwright E2E FAILED${NC}"
    echo "$SUMMARY" | grep -v "^$" | sed 's/^FAIL=/  ✘ /'
    echo -e "    Full JSON report: ${LOG_DIR}/playwright_last.json"
    echo -e "    Stdout log:       ${LOG_DIR}/playwright_stdout.log"
fi

exit $PW_EXIT
