#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  Cloud_IOT — CodeRabbit AI Code Review
#
#  Called by the pre-push hook AFTER pytest passes.
#  Reviews the diff between local HEAD and the remote branch.
#  Blocks the push if CodeRabbit reports any CRITICAL issues.
#
#  Requires:
#    npm install -g @coderabbitai/coderabbit-cli
#    export CODERABBIT_API_KEY="your-key"
#
#  Usage:
#    bash tests/coderabbit_review.sh [base_ref]
#    base_ref defaults to origin/main
# ─────────────────────────────────────────────────────────────────────────────
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_DIR="${ROOT_DIR}/tests/logs"
LOG_FILE="${LOG_DIR}/coderabbit_$(date +%Y%m%d_%H%M%S).log"
SUMMARY_FILE="${LOG_DIR}/coderabbit_last.log"

mkdir -p "$LOG_DIR"

BASE_REF="${1:-origin/main}"

YELLOW='\033[1;33m'; RED='\033[0;31m'; GREEN='\033[0;32m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

echo ""
echo -e "${CYAN}${BOLD}── CodeRabbit AI Review ──────────────────────────────────${NC}"

# ── Sanity checks ─────────────────────────────────────────────────────────────

if ! command -v coderabbit &>/dev/null; then
    echo -e "${YELLOW}[!] CodeRabbit CLI not found — skipping AI review.${NC}"
    echo -e "    Install: npm install -g @coderabbitai/coderabbit-cli"
    echo -e "    Then set: export CODERABBIT_API_KEY=<your-key>"
    echo ""
    exit 0
fi

if [ -z "${CODERABBIT_API_KEY:-}" ]; then
    echo -e "${YELLOW}[!] CODERABBIT_API_KEY not set — skipping AI review.${NC}"
    echo -e "    Get your key at https://coderabbit.ai and set:"
    echo -e "    export CODERABBIT_API_KEY=<your-key>"
    echo ""
    exit 0
fi

# ── Generate diff ─────────────────────────────────────────────────────────────

echo -e "  Base : ${BOLD}${BASE_REF}${NC}"
echo -e "  Head : ${BOLD}$(git rev-parse --short HEAD)${NC} $(git log -1 --format='%s')"
echo ""

# Fetch remote silently so we have the latest refs
git fetch origin --quiet 2>/dev/null || true

DIFF=$(git diff "${BASE_REF}"...HEAD 2>/dev/null)

if [ -z "$DIFF" ]; then
    echo -e "${GREEN}[✔] No diff vs ${BASE_REF} — nothing to review.${NC}"
    echo ""
    exit 0
fi

CHANGED_FILES=$(git diff --name-only "${BASE_REF}"...HEAD 2>/dev/null | wc -l | tr -d ' ')
DIFF_LINES=$(echo "$DIFF" | wc -l | tr -d ' ')
echo -e "  Reviewing ${BOLD}${CHANGED_FILES} files${NC}, ${DIFF_LINES} diff lines..."
echo ""

# ── Run CodeRabbit review ─────────────────────────────────────────────────────

REVIEW_OUTPUT=""
CR_EXIT=0

# Pipe the diff to coderabbit; capture JSON output
REVIEW_OUTPUT=$(echo "$DIFF" | coderabbit review \
    --input-format diff \
    --output-format json \
    --api-key "${CODERABBIT_API_KEY}" \
    2>&1) || CR_EXIT=$?

# Save full output for debugging
echo "$REVIEW_OUTPUT" > "$LOG_FILE"
echo "$REVIEW_OUTPUT" > "$SUMMARY_FILE"

# ── Parse results using Python (already in venv) ──────────────────────────────

PYTHON_BIN="${ROOT_DIR}/backend/.venv/Scripts/python.exe"
[ -f "$PYTHON_BIN" ] || PYTHON_BIN="${ROOT_DIR}/backend/.venv/bin/python"
[ -f "$PYTHON_BIN" ] || PYTHON_BIN="python3"

PARSE_RESULT=$("$PYTHON_BIN" - "$REVIEW_OUTPUT" <<'PYEOF'
import sys, json, re

raw = sys.argv[1] if len(sys.argv) > 1 else ""

# Try to extract JSON from the output (CR may prefix with text)
json_match = re.search(r'\{.*\}|\[.*\]', raw, re.DOTALL)
if not json_match:
    print("PARSE_ERROR")
    sys.exit(0)

try:
    data = json.loads(json_match.group())
except json.JSONDecodeError:
    print("PARSE_ERROR")
    sys.exit(0)

# Normalise: CR may return a list of issues or a dict with "issues" key
issues = data if isinstance(data, list) else data.get("issues", data.get("findings", []))

critical_severities = {"critical", "error", "blocker"}
warning_severities  = {"high", "warning", "major"}

critical = [i for i in issues if str(i.get("severity", "")).lower() in critical_severities]
warnings = [i for i in issues if str(i.get("severity", "")).lower() in warning_severities]
infos    = [i for i in issues if str(i.get("severity", "")).lower() not in critical_severities | warning_severities]

print(f"CRITICAL={len(critical)}")
print(f"WARNINGS={len(warnings)}")
print(f"INFO={len(infos)}")

for i, issue in enumerate(critical, 1):
    file_  = issue.get("file", issue.get("path", "?"))
    line_  = issue.get("line", issue.get("line_number", "?"))
    msg    = issue.get("message", issue.get("description", issue.get("title", "no message")))
    rule   = issue.get("rule", issue.get("type", ""))
    print(f"CRIT_ISSUE_{i}={file_}:{line_} [{rule}] {msg}")

for i, issue in enumerate(warnings, 1):
    file_  = issue.get("file", issue.get("path", "?"))
    line_  = issue.get("line", issue.get("line_number", "?"))
    msg    = issue.get("message", issue.get("description", issue.get("title", "no message")))
    print(f"WARN_ISSUE_{i}={file_}:{line_} {msg}")
PYEOF
2>/dev/null || echo "PARSE_ERROR")

# ── Display results ───────────────────────────────────────────────────────────

if [[ "$PARSE_RESULT" == *"PARSE_ERROR"* ]]; then
    echo -e "${YELLOW}[!] Could not parse CodeRabbit output (non-JSON response).${NC}"
    echo -e "    Raw output saved to: ${LOG_FILE}"
    echo -e "    Review manually before pushing."
    echo ""
    # Do not block — parsing failure should not stop deployment
    exit 0
fi

CRITICAL_COUNT=$(echo "$PARSE_RESULT" | grep "^CRITICAL=" | cut -d= -f2)
WARNINGS_COUNT=$(echo "$PARSE_RESULT" | grep "^WARNINGS=" | cut -d= -f2)
INFO_COUNT=$(echo "$PARSE_RESULT"     | grep "^INFO="     | cut -d= -f2)

CRITICAL_COUNT=${CRITICAL_COUNT:-0}
WARNINGS_COUNT=${WARNINGS_COUNT:-0}
INFO_COUNT=${INFO_COUNT:-0}

echo -e "  Results:"
echo -e "    ${RED}Critical : ${CRITICAL_COUNT}${NC}"
echo -e "    ${YELLOW}Warnings : ${WARNINGS_COUNT}${NC}"
echo -e "    Info     : ${INFO_COUNT}"
echo ""

# Print critical issues
if [ "$CRITICAL_COUNT" -gt 0 ]; then
    echo -e "${RED}${BOLD}  ── Critical Issues (must fix before push) ──────────────${NC}"
    echo "$PARSE_RESULT" | grep "^CRIT_ISSUE_" | while IFS='=' read -r key val; do
        echo -e "    ${RED}✘${NC} ${val}"
    done
    echo ""
fi

# Print warnings
if [ "$WARNINGS_COUNT" -gt 0 ]; then
    echo -e "${YELLOW}  ── Warnings (review recommended) ───────────────────────${NC}"
    echo "$PARSE_RESULT" | grep "^WARN_ISSUE_" | while IFS='=' read -r key val; do
        echo -e "    ${YELLOW}!${NC} ${val}"
    done
    echo ""
fi

echo -e "  Full report: ${LOG_FILE}"
echo ""

# ── Decision ──────────────────────────────────────────────────────────────────

if [ "$CRITICAL_COUNT" -gt 0 ]; then
    echo -e "${RED}${BOLD}╔══════════════════════════════════════════════════════╗${NC}"
    echo -e "${RED}${BOLD}║  PUSH BLOCKED — ${CRITICAL_COUNT} critical issue(s) found by CodeRabbit  ║${NC}"
    echo -e "${RED}${BOLD}╚══════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "  Fix the issues above, then commit and push again."
    echo -e "  To bypass (emergencies only): git push --no-verify"
    echo ""
    exit 1
fi

if [ "$WARNINGS_COUNT" -gt 0 ]; then
    echo -e "${YELLOW}[!] ${WARNINGS_COUNT} warning(s) found — review recommended but push allowed.${NC}"
fi

echo -e "${GREEN}[✔] CodeRabbit review passed — proceeding with push.${NC}"
echo ""
exit 0
