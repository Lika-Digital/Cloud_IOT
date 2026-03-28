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

YELLOW='\\033[1;33m'; RED='\\033[0;31m'; GREEN='\\033[0;32m'
CYAN='\\033[0;36m'; BOLD='\\033[1m'; NC='\\033[0m'

LOG_DIR="${SCRIPT_DIR}/logs"
mkdir -p "$LOG_DIR"

echo ""
echo -e "${CYAN}${BOLD}[E2E] Playwright end-to-end tests${NC}"
echo ""

# ── Check Node / npm are available ────────────────────────────────────────────
if ! command -v node &>/dev/null; then
    echo -e "${YELLOW}[!] Node.js not found — skipping Playwright.${NC}"
    exit 0
fi

# ── Check frontend deps are installed ─────────────────────────────────────────
if [ ! -d "frontend/node_modules/@playwright" ]; then
    echo -e "${YELLOW}[!] Playwright not installed in frontend/node_modules.${NC}"
    echo "    Run: cd frontend && npm install"
    exit 0
fi

# ── Run Playwright ─────────────────────────────────────────────────────────────
cd frontend
npx playwright test \
    --reporter=list \
    --reporter=json:"../tests/logs/playwright_last.json" \
    2>&1 | tee "../tests/logs/playwright_stdout.log"
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
