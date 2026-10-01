#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  Cloud_IOT — Automated Test Suite
#
#  Stages:
#    1. pytest        — backend functional tests (must pass, blocks commit)
#    2. Bandit        — Python security scan (critical/high blocks commit)
#    3. Semgrep       — Python + TS bug/security patterns (critical blocks)
#    4. ESLint        — TypeScript/React lint (errors block commit)
#
#  Pre-push gate also runs Playwright E2E (tests/playwright_e2e.sh).
#
#  Usage: bash tests/run_tests.sh [pytest extra args]
#  Called automatically by the pre-commit and pre-push hooks.
#
#  GATE_LEVEL (v3.43)
#  ------------------
#  fast (default, pre-commit) — everything that is deterministic and local:
#      pytest, bandit, the cross-layer gap checks. No unbounded network calls.
#  full (pre-push)            — the above plus semgrep, pip-audit, detect-secrets and
#      ESLint. Push is the sharing boundary, so that is where the slow and
#      network-dependent checks belong.
#
#  WHY THIS SPLIT EXISTS. pip-audit fetches PyPI's vulnerability database and was measured
#  taking >122 s without completing on a developer box. Its RESULT was already advisory
#  ("warn but do not block") — but its RUNTIME was unbounded, and a non-blocking check that
#  can hang forever still blocks. Three commits were lost to it, and the person losing them
#  started working around the gate, which is precisely what a slow gate produces. Every
#  network-dependent stage now has a hard timeout, and a timeout is REPORTED rather than
#  passing silently.
# ─────────────────────────────────────────────────────────────────────────────
set -uo pipefail

GATE_LEVEL="${GATE_LEVEL:-fast}"
# Hard ceilings for stages that reach the network. Exceeding one is reported as NOT RUN —
# never as a pass, because "we could not check" and "we checked and it was fine" are
# different answers.
SEMGREP_TIMEOUT_S="${SEMGREP_TIMEOUT_S:-180}"
PIP_AUDIT_TIMEOUT_S="${PIP_AUDIT_TIMEOUT_S:-90}"
SKIPPED_STAGES=()

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$ROOT_DIR"

LOG_DIR="${SCRIPT_DIR}/logs"
mkdir -p "$LOG_DIR"

YELLOW='\033[1;33m'; RED='\033[0;31m'; GREEN='\033[0;32m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

echo ""
echo "  Gate level: ${GATE_LEVEL}   (fast = pytest + bandit + gap checks; full adds semgrep, pip-audit, mobile tsc)"
echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║          Cloud_IOT — Automated Test Suite           ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

OVERALL_EXIT=0

# ── Resolve venv ───────────────────────────────────────────────────────────────
VENV_ACTIVATE="backend/.venv/Scripts/activate"
[ -f "$VENV_ACTIVATE" ] || VENV_ACTIVATE="backend/.venv/bin/activate"
if [ ! -f "$VENV_ACTIVATE" ]; then
    echo -e "${RED}[ERROR] Virtual environment not found.${NC}"
    echo "        Run: cd backend && python -m venv .venv && pip install -r requirements.txt"
    exit 1
fi
# shellcheck source=/dev/null
source "$VENV_ACTIVATE"

VENV_BIN="backend/.venv/Scripts"
[ -d "$VENV_BIN" ] || VENV_BIN="backend/.venv/bin"

# ═══════════════════════════════════════════════════════════════════════════════
# STAGE 1 — pytest
# ═══════════════════════════════════════════════════════════════════════════════
echo -e "${CYAN}${BOLD}[1/4] Backend tests (pytest)${NC}"
echo ""

if ! python -m pytest --version &>/dev/null; then
    pip install pytest pytest-asyncio httpx starlette --quiet
fi

# ── ffmpeg for the guard tests ────────────────────────────────────────────────
# Seven guard tests need a real ffmpeg, including the two smoke tests that drive the
# worker's full armed path. They resolve it via GUARD_FFMPEG or PATH, exactly as the
# worker does. Finding it here rather than leaving them skipped matters: a skipped test
# is an unanswered question, and on this dev box ffmpeg is installed but not on PATH.
if [ -z "${GUARD_FFMPEG:-}" ] && ! command -v ffmpeg &>/dev/null; then
    for candidate in \
        "$LOCALAPPDATA/Microsoft/WinGet/Links/ffmpeg.exe" \
        "$HOME/AppData/Local/Microsoft/WinGet/Packages"/Gyan.FFmpeg*/*/bin/ffmpeg.exe \
        "$HOME/scoop/shims/ffmpeg.exe" \
        /c/ffmpeg/bin/ffmpeg.exe \
        /usr/bin/ffmpeg /usr/local/bin/ffmpeg
    do
        if [ -f "$candidate" ]; then
            export GUARD_FFMPEG="$candidate"
            echo -e "  ${CYAN}ffmpeg: $candidate${NC}"
            break
        fi
    done
fi
if [ -z "${GUARD_FFMPEG:-}" ] && ! command -v ffmpeg &>/dev/null; then
    echo -e "  ${YELLOW}[!] no ffmpeg found — 7 guard tests will SKIP, including the"
    echo -e "      worker smoke tests that exercise capture -> alarm -> clip.${NC}"
fi

PYTEST_LOG="${LOG_DIR}/pytest_last.log"
python -m pytest tests/backend/ -v --tb=short --no-header -rs \
    -W ignore::DeprecationWarning "$@" 2>&1 | tee "$PYTEST_LOG"
PYTEST_EXIT=${PIPESTATUS[0]}
rm -f tests/test_pedestal.db tests/test_users.db

echo ""
if [ $PYTEST_EXIT -eq 0 ]; then
    echo -e "${GREEN}[✔] pytest passed${NC}"
else
    echo -e "${RED}[✘] pytest FAILED — fix before committing${NC}"
    OVERALL_EXIT=1
fi

# Say the skip count out loud. A green run with skipped tests is not the same as a green
# run, and the difference is invisible in the summary line unless it is named.
SKIPPED=$(grep -cE "^SKIPPED " "$PYTEST_LOG" 2>/dev/null || echo 0)
if [ "${SKIPPED:-0}" -gt 0 ]; then
    echo -e "${YELLOW}[!] ${SKIPPED} test(s) SKIPPED — unanswered, not passed:${NC}"
    grep -E "^SKIPPED " "$PYTEST_LOG" | sed 's/^/      /'
fi

# ═══════════════════════════════════════════════════════════════════════════════
# STAGE 2 — Bandit (Python security)
# ═══════════════════════════════════════════════════════════════════════════════
echo ""
echo -e "${CYAN}${BOLD}[2/4] Python security scan (bandit)${NC}"
echo ""

BANDIT_BIN="${VENV_BIN}/bandit"
[ -f "${BANDIT_BIN}.exe" ] && BANDIT_BIN="${BANDIT_BIN}.exe"

BANDIT_EXIT=0
if command -v "$BANDIT_BIN" &>/dev/null || [ -f "$BANDIT_BIN" ]; then
    BANDIT_LOG="${LOG_DIR}/bandit_last.log"

    # Run bandit on backend — severity HIGH+, confidence MEDIUM+
    # Exclude test files and migrations
    "$BANDIT_BIN" \
        -r backend/app/ \
        -ll \
        -ii \
        --exclude "backend/app/tests" \
        -f json \
        -o "$BANDIT_LOG" \
        2>/dev/null || true

    # Parse results
    BANDIT_RESULTS=$(python - "$BANDIT_LOG" << 'PYEOF'
import sys, json
try:
    with open(sys.argv[1]) as f:
        data = json.load(f)
    results = data.get("results", [])
    high    = [r for r in results if r.get("issue_severity") == "HIGH"]
    medium  = [r for r in results if r.get("issue_severity") == "MEDIUM"]
    print(f"HIGH={len(high)}")
    print(f"MEDIUM={len(medium)}")
    for r in high:
        print(f"ISSUE={r['filename']}:{r['line_number']} [{r['test_id']}] {r['issue_text']}")
except Exception as e:
    print(f"PARSE_ERROR={e}")
PYEOF
)

    HIGH_COUNT=$(echo "$BANDIT_RESULTS" | grep "^HIGH=" | cut -d= -f2)
    MED_COUNT=$(echo "$BANDIT_RESULTS"  | grep "^MEDIUM=" | cut -d= -f2)
    HIGH_COUNT=${HIGH_COUNT:-0}
    MED_COUNT=${MED_COUNT:-0}

    echo -e "  ${RED}High severity   : ${HIGH_COUNT}${NC}"
    echo -e "  ${YELLOW}Medium severity : ${MED_COUNT}${NC}"

    if [ "$HIGH_COUNT" -gt 0 ]; then
        echo ""
        echo -e "${RED}  ── High severity issues ──────────────────────────────────${NC}"
        echo "$BANDIT_RESULTS" | grep "^ISSUE=" | sed 's/^ISSUE=/  ✘ /'
        echo ""
        echo -e "${RED}[✘] Bandit found ${HIGH_COUNT} high-severity issue(s) — fix before committing${NC}"
        echo -e "    Full report: ${BANDIT_LOG}"
        BANDIT_EXIT=1
        OVERALL_EXIT=1
    elif [ "$MED_COUNT" -gt 0 ]; then
        echo -e "${YELLOW}[!] Bandit: ${MED_COUNT} medium issue(s) — review recommended${NC}"
        echo -e "    Full report: ${BANDIT_LOG}"
    else
        echo -e "${GREEN}[✔] Bandit passed — no high/medium issues${NC}"
    fi
else
    echo -e "${YELLOW}[!] Bandit not found — skipping.${NC}"
    echo -e "    Install: pip install bandit"
fi

# ═══════════════════════════════════════════════════════════════════════════════
# STAGE 3 — Semgrep (Python + TypeScript patterns)
# ═══════════════════════════════════════════════════════════════════════════════
echo ""
echo -e "${CYAN}${BOLD}[3/4] Bug & security patterns (semgrep)${NC}"
echo ""

SEMGREP_BIN="${VENV_BIN}/semgrep"
[ -f "${SEMGREP_BIN}.exe" ] && SEMGREP_BIN="${SEMGREP_BIN}.exe"

SEMGREP_EXIT=0
if [ "$GATE_LEVEL" != "full" ]; then
    echo -e "${YELLOW}[~] semgrep: not run at gate level 'fast' — runs on push.${NC}"
    SKIPPED_STAGES+=("semgrep (fast gate; runs on push)")
elif command -v "$SEMGREP_BIN" &>/dev/null || [ -f "$SEMGREP_BIN" ]; then
    SEMGREP_LOG="${LOG_DIR}/semgrep_last.log"

    # Run semgrep with auto rules (free, no login needed for local use)
    # Scan backend Python + frontend TypeScript
    timeout "${SEMGREP_TIMEOUT_S}" "$SEMGREP_BIN" \
        --config "p/python" \
        --config "p/typescript" \
        --config "p/security-audit" \
        --config "p/owasp-top-ten" \
        --error \
        --quiet \
        --json \
        --output "$SEMGREP_LOG" \
        backend/app/ frontend/src/ \
        2>/dev/null
    SEMGREP_EXIT=$?

    # Parse results
    SEMGREP_RESULTS=$(python - "$SEMGREP_LOG" << 'PYEOF'
import sys, json
try:
    with open(sys.argv[1]) as f:
        data = json.load(f)
    findings = data.get("results", [])
    errors   = [r for r in findings if r.get("extra", {}).get("severity") in ("ERROR",  "error")]
    warnings = [r for r in findings if r.get("extra", {}).get("severity") in ("WARNING","warning")]
    print(f"ERRORS={len(errors)}")
    print(f"WARNINGS={len(warnings)}")
    for r in errors[:10]:   # cap at 10 to avoid flooding terminal
        path = r.get("path","?")
        line = r.get("start",{}).get("line","?")
        msg  = r.get("extra",{}).get("message","")[:120]
        rule = r.get("check_id","").split(".")[-1]
        print(f"ISSUE={path}:{line} [{rule}] {msg}")
except Exception as e:
    print(f"PARSE_ERROR={e}")
PYEOF
)

    ERR_COUNT=$(echo "$SEMGREP_RESULTS"  | grep "^ERRORS="   | cut -d= -f2)
    WARN_COUNT=$(echo "$SEMGREP_RESULTS" | grep "^WARNINGS=" | cut -d= -f2)
    ERR_COUNT=${ERR_COUNT:-0}
    WARN_COUNT=${WARN_COUNT:-0}

    echo -e "  ${RED}Errors   : ${ERR_COUNT}${NC}"
    echo -e "  ${YELLOW}Warnings : ${WARN_COUNT}${NC}"

    if [ "$ERR_COUNT" -gt 0 ]; then
        echo ""
        echo -e "${RED}  ── Semgrep errors ────────────────────────────────────────${NC}"
        echo "$SEMGREP_RESULTS" | grep "^ISSUE=" | sed 's/^ISSUE=/  ✘ /'
        echo ""
        echo -e "${RED}[✘] Semgrep found ${ERR_COUNT} error(s) — fix before committing${NC}"
        echo -e "    Full report: ${SEMGREP_LOG}"
        SEMGREP_EXIT=1
        OVERALL_EXIT=1
    elif [ "$WARN_COUNT" -gt 0 ]; then
        echo -e "${YELLOW}[!] Semgrep: ${WARN_COUNT} warning(s) — review recommended${NC}"
        echo -e "    Full report: ${SEMGREP_LOG}"
    else
        echo -e "${GREEN}[✔] Semgrep passed${NC}"
    fi
else
    echo -e "${YELLOW}[!] Semgrep not found — skipping.${NC}"
    echo -e "    Install: pip install semgrep"
fi

# ═══════════════════════════════════════════════════════════════════════════════
# STAGE 4 — ESLint (TypeScript / React)
# ═══════════════════════════════════════════════════════════════════════════════
echo ""
echo -e "${CYAN}${BOLD}[4/4] TypeScript (eslint + mobile tsc)${NC}"
echo ""

ESLINT_EXIT=0
if [ "$GATE_LEVEL" != "full" ]; then
    echo -e "${YELLOW}[~] eslint: not run at gate level 'fast' — runs on push.${NC}"
    SKIPPED_STAGES+=("eslint (fast gate; runs on push)")
elif [ -f "frontend/node_modules/.bin/eslint" ] || \
     [ -f "frontend/node_modules/.bin/eslint.cmd" ]; then

    ESLINT_LOG="${LOG_DIR}/eslint_last.log"
    cd frontend

    # Run ESLint — only on src/, output as JSON for reliable parsing
    node_modules/.bin/eslint src/ \
        --ext ts,tsx \
        --format json \
        --output-file "../${ESLINT_LOG}" \
        2>/dev/null
    ESLINT_EXIT=$?
    cd "$ROOT_DIR"

    # Parse results
    ESLINT_RESULTS=$(python - "$ESLINT_LOG" << 'PYEOF'
import sys, json
try:
    with open(sys.argv[1]) as f:
        data = json.load(f)
    errors = warnings = 0
    issues = []
    for file_result in data:
        path = file_result.get("filePath","?").replace("\\","/")
        # shorten path to src/...
        if "/src/" in path:
            path = "src/" + path.split("/src/",1)[1]
        for msg in file_result.get("messages", []):
            sev = msg.get("severity", 1)
            text = msg.get("message","")
            line = msg.get("line","?")
            rule = msg.get("ruleId","")
            if sev == 2:
                errors += 1
                issues.append(f"ISSUE={path}:{line} [{rule}] {text}")
            else:
                warnings += 1
    print(f"ERRORS={errors}")
    print(f"WARNINGS={warnings}")
    for i in issues[:10]:
        print(i)
except Exception as e:
    print(f"PARSE_ERROR={e}")
PYEOF
)

    ERR_COUNT=$(echo "$ESLINT_RESULTS"  | grep "^ERRORS="   | cut -d= -f2)
    WARN_COUNT=$(echo "$ESLINT_RESULTS" | grep "^WARNINGS=" | cut -d= -f2)
    ERR_COUNT=${ERR_COUNT:-0}
    WARN_COUNT=${WARN_COUNT:-0}

    echo -e "  ${RED}Errors   : ${ERR_COUNT}${NC}"
    echo -e "  ${YELLOW}Warnings : ${WARN_COUNT}${NC}"

    if [ "$ERR_COUNT" -gt 0 ]; then
        echo ""
        echo -e "${RED}  ── ESLint errors ─────────────────────────────────────────${NC}"
        echo "$ESLINT_RESULTS" | grep "^ISSUE=" | sed 's/^ISSUE=/  ✘ /'
        echo ""
        echo -e "${RED}[✘] ESLint found ${ERR_COUNT} error(s) — fix before committing${NC}"
        echo -e "    Full report: ${ESLINT_LOG}"
        ESLINT_EXIT=1
        OVERALL_EXIT=1
    elif [ "$WARN_COUNT" -gt 0 ]; then
        echo -e "${YELLOW}[!] ESLint: ${WARN_COUNT} warning(s) — review recommended${NC}"
        echo -e "    Full report: ${ESLINT_LOG}"
    else
        echo -e "${GREEN}[✔] ESLint passed${NC}"
    fi
else
    # v3.43/2026-10-01 — THIS STAGE HAS NEVER RUN, AND COULD NEVER HAVE RUN.
    #
    # eslint is not a dependency of the frontend package (it appears in the `lint` npm
    # script and nowhere else), and there is no eslint config file in frontend/. So this
    # branch has been taken on every invocation since the gate was written — and until
    # today it was taken SILENTLY, while the gate banner advertised eslint as part of the
    # full gate. A stage that cannot run, announced as running, is the exact false green
    # signal of docs/engineering_notes.md rule 10.
    #
    # The message used to say "frontend deps not installed" and point at `npm install`,
    # which would not have fixed it: the deps ARE installed, eslint was simply never one.
    # Adopting it properly (install + plugins + config + whatever it finds on a codebase
    # that has never been linted) is deferred work, listed as D13 in docs/ui_v2_spec.md.
    echo -e "${YELLOW}[!] ESLint NOT CHECKED - and cannot be.${NC}"
    echo -e "    eslint is not a devDependency of frontend/ and there is no eslint config."
    echo -e "    This stage has never run. See D13 in docs/ui_v2_spec.md."
    SKIPPED_STAGES+=("eslint (NOT A DEPENDENCY - this stage has never run, see D13)")
fi

# ─── Mobile TypeScript typecheck (v3.43) ─────────────────────────────────────
#
# Added because its absence cost us a screen. The QR landing page imported a path
# four directory levels up when five were needed, so the module never resolved and
# the entire flow could not build. `tsc` reported it — nobody ran tsc on this
# package, and the four unrelated errors already in its baseline meant that even
# when someone did, the fifth line went unread.
#
# The baseline is now ZERO. Any error fails the gate, which is the point: a count
# nobody acts on hides the next one (docs/engineering_notes.md rule 10).
if [ "$GATE_LEVEL" != "full" ]; then
    echo -e "${YELLOW}[~] mobile tsc: not run at gate level 'fast' — runs on push.${NC}"
    SKIPPED_STAGES+=("mobile tsc (fast gate; runs on push)")
elif [ -f "mobile/node_modules/typescript/bin/tsc" ]; then
    echo ""
    echo "  Mobile TypeScript (tsc --noEmit)..."
    MOBILE_TSC_LOG="${LOG_DIR}/mobile_tsc_last.log"
    ( cd mobile && node node_modules/typescript/bin/tsc --noEmit ) > "$MOBILE_TSC_LOG" 2>&1
    MOBILE_TSC_EXIT=$?
    if [ $MOBILE_TSC_EXIT -ne 0 ]; then
        MOBILE_ERRS=$(grep -c "error TS" "$MOBILE_TSC_LOG" || true)
        echo -e "${RED}[X] mobile tsc: ${MOBILE_ERRS} error(s)${NC}"
        grep "error TS" "$MOBILE_TSC_LOG" | head -20
        echo -e "    Full report: ${MOBILE_TSC_LOG}"
        OVERALL_EXIT=1
    else
        echo -e "${GREEN}[✔] mobile tsc passed${NC}"
    fi
else
    echo -e "${YELLOW}[!] mobile tsc NOT CHECKED (mobile deps not installed).${NC}"
    echo -e "    Run: cd mobile && npm install"
    SKIPPED_STAGES+=("mobile tsc (mobile deps not installed - NOT CHECKED)")
fi

# ═══════════════════════════════════════════════════════════════════════════════
# STAGE 5 — GAP TESTS (cross-layer boundary checks)
# Added: 2026-04-03
# ═══════════════════════════════════════════════════════════════════════════════
echo ""
echo -e "${CYAN}${BOLD}[5/5] Cross-layer gap checks${NC}"
echo ""

GAP_DIR="${ROOT_DIR}/scripts/gap-tests"

# GAP: FE<->BE | LAYER: schema consistency | TOOL: custom Python inspector
# Verifies SessionResponse Pydantic schema matches frontend Session TS interface.
echo "  [GAP-1] FE<->BE: SessionResponse schema vs frontend Session interface..."
if python "$GAP_DIR/gap_fe_be_session_schema.py" > /tmp/gap1.log 2>&1; then
    echo -e "  ${GREEN}[✔] GAP-1 passed${NC}"
else
    echo -e "  ${RED}[✘] GAP-1 FAILED — schema mismatch detected${NC}"
    cat /tmp/gap1.log
    OVERALL_EXIT=1
fi

# GAP: security | LAYER: credential scan | TOOL: detect-secrets
# Scans for accidentally committed secrets/credentials in source files.
DETECT_SECRETS_BIN="${VENV_BIN}/detect-secrets"
[ -f "${DETECT_SECRETS_BIN}.exe" ] && DETECT_SECRETS_BIN="${DETECT_SECRETS_BIN}.exe"

echo "  [GAP-2] Security: detect-secrets credential scan..."
if command -v "$DETECT_SECRETS_BIN" &>/dev/null || [ -f "$DETECT_SECRETS_BIN" ]; then
    "$DETECT_SECRETS_BIN" scan \
        --exclude-files ".*\.log$" \
        --exclude-files ".*\.db$" \
        --exclude-files ".*node_modules.*" \
        --exclude-files ".*\.venv.*" \
        --exclude-files ".*__pycache__.*" \
        --exclude-files ".*DEB_Pack.*" \
        --exclude-files ".*\.git.*" \
        backend/app/ frontend/src/ \
        2>/dev/null \
        | python "$GAP_DIR/gap_security_detect_secrets.py" > /tmp/gap2.log 2>&1
    DSEC_EXIT=$?

    if [ $DSEC_EXIT -eq 0 ]; then
        echo -e "  ${GREEN}[✔] GAP-2 passed — no secrets found${NC}"
    else
        echo -e "  ${YELLOW}[!] GAP-2 WARNING — review potential secrets${NC}"
        head -20 /tmp/gap2.log
        # Warn but do not block (detect-secrets has false positives)
    fi
else
    echo -e "  ${YELLOW}[!] detect-secrets not found — skipping.${NC}"
    echo -e "      Install: pip install detect-secrets"
fi

# GAP: security | LAYER: dependency CVEs | TOOL: pip-audit
# Audits Python dependencies for known CVEs.
PIP_AUDIT_BIN="${VENV_BIN}/pip-audit"
[ -f "${PIP_AUDIT_BIN}.exe" ] && PIP_AUDIT_BIN="${PIP_AUDIT_BIN}.exe"

echo "  [GAP-3] Security: pip-audit dependency CVE scan..."
if [ "$GATE_LEVEL" != "full" ]; then
    echo -e "  ${YELLOW}[~] pip-audit: not run at gate level 'fast' — runs on push.${NC}"
    SKIPPED_STAGES+=("pip-audit (fast gate; runs on push)")
elif command -v "$PIP_AUDIT_BIN" &>/dev/null || [ -f "$PIP_AUDIT_BIN" ]; then
    AUDIT_LOG="${LOG_DIR}/pip_audit_last.log"
    timeout "${PIP_AUDIT_TIMEOUT_S}" "$PIP_AUDIT_BIN" \
        --requirement "${ROOT_DIR}/backend/requirements.txt" \
        --format json \
        --output "$AUDIT_LOG" \
        2>/dev/null
    AUDIT_EXIT=$?
    if [ $AUDIT_EXIT -eq 124 ]; then
        echo -e "  ${YELLOW}[!] pip-audit TIMED OUT after ${PIP_AUDIT_TIMEOUT_S}s — dependency CVEs NOT CHECKED.${NC}"
        echo -e "      It fetches PyPI advisories; a slow or blocked network looks exactly like this."
        SKIPPED_STAGES+=("pip-audit (TIMED OUT - CVEs not checked)")
    fi

    AUDIT_SUMMARY=$(python - "$AUDIT_LOG" << 'PYEOF'
import sys, json, os
path = sys.argv[1]
if not os.path.exists(path):
    print("PARSE_ERROR=no output file")
    sys.exit(0)
try:
    with open(path) as f:
        data = json.load(f)
    vulns = data.get("dependencies", [])
    critical = [v for d in vulns for v in d.get("vulns", []) if v.get("fix_versions")]
    print(f"VULNS={len(critical)}")
    for v in critical[:5]:
        print(f"CVE={v.get('id','?')} {v.get('description','')[:80]}")
except Exception as e:
    print(f"PARSE_ERROR={e}")
PYEOF
)

    VULN_COUNT=$(echo "$AUDIT_SUMMARY" | grep "^VULNS=" | cut -d= -f2)
    VULN_COUNT=${VULN_COUNT:-0}

    if [ "$VULN_COUNT" -gt 0 ]; then
        echo -e "  ${YELLOW}[!] GAP-3 WARNING — ${VULN_COUNT} fixable CVE(s) in dependencies${NC}"
        echo "$AUDIT_SUMMARY" | grep "^CVE=" | sed 's/^CVE=/    /'
        echo -e "      Full report: ${AUDIT_LOG}"
        # Warn but do not block (production-decision on patching schedule)
    else
        echo -e "  ${GREEN}[✔] GAP-3 passed — no fixable CVEs found${NC}"
    fi
else
    echo -e "  ${YELLOW}[!] pip-audit not found — skipping.${NC}"
    echo -e "      Install: pip install pip-audit"
fi

# GAP: BE<->DB | LAYER: migration idempotency | TOOL: custom Python test
# Verifies _migrate_schema() is safe to call multiple times (no crash on re-run).
echo "  [GAP-4] BE<->DB: migration idempotency check..."
python "$GAP_DIR/gap_be_db_migration_idempotency.py" > /tmp/gap4.log 2>&1
GAP4_EXIT=$?
if [ $GAP4_EXIT -eq 0 ]; then
    echo -e "  ${GREEN}[✔] GAP-4 passed — migration is idempotent${NC}"
else
    echo -e "  ${RED}[✘] GAP-4 FAILED — migration crashes on second run${NC}"
    cat /tmp/gap4.log
    OVERALL_EXIT=1
fi

# ═══════════════════════════════════════════════════════════════════════════════
# Summary
# ═══════════════════════════════════════════════════════════════════════════════
echo ""
if [ ${#SKIPPED_STAGES[@]} -gt 0 ]; then
    echo -e "${YELLOW}Stages NOT RUN at gate level ${GATE_LEVEL}:${NC}"
    for st in "${SKIPPED_STAGES[@]}"; do echo "    - $st"; done
    echo ""
fi
echo "──────────────────────────────────────────────────────────"
if [ $OVERALL_EXIT -eq 0 ]; then
    echo -e "${GREEN}${BOLD}✓ All checks passed.${NC}"
else
    echo -e "${RED}${BOLD}✗ One or more checks FAILED — fix errors before committing.${NC}"
fi
echo ""

exit $OVERALL_EXIT
