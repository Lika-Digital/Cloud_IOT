#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  Install the Cloud_IOT git hooks.
#
#  WHY THIS EXISTS. `.git/hooks/` is not tracked by git, so the hooks are per-clone. That
#  means a gate improvement made on one machine does not reach anyone else, and a fresh clone
#  has no gate at all — it commits with nothing checked and looks identical to a clone that
#  passed. Running this after cloning is what makes the gate real.
#
#  Usage:  bash scripts/install_git_hooks.sh
#  Idempotent: safe to re-run; it overwrites the two hook files.
#
#  THE GATE SPLIT (v3.43)
#  ----------------------
#  pre-commit -> GATE_LEVEL=fast : pytest + bandit + the cross-layer gap checks. ~4.5 min,
#                                  bounded, no unbounded network calls.
#  pre-push   -> GATE_LEVEL=full : the above plus semgrep, pip-audit, ESLint, Playwright.
#
#  The split came from a measured failure, not a preference: pip-audit fetches PyPI's advisory
#  database and was measured at >122 s without completing. Its result was already advisory
#  ("warn but do not block") while its runtime was unbounded — and a non-blocking check that
#  can hang forever still blocks. Three commits were lost to it and the author started working
#  around the gate, which is what a slow gate always produces.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOOKS="$ROOT/.git/hooks"

if [ ! -d "$ROOT/.git" ]; then
    echo "Not a git working tree: $ROOT" >&2
    exit 1
fi
mkdir -p "$HOOKS"

cat > "$HOOKS/pre-commit" <<'HOOK'
#!/usr/bin/env bash
# Installed by scripts/install_git_hooks.sh — edit there, not here, or the change is lost.
REPO_ROOT="$(git rev-parse --show-toplevel)"

echo ""
echo "🔍 Pre-commit: fast gate (pytest + bandit + gap checks)"
echo ""

GATE_LEVEL=fast bash "$REPO_ROOT/tests/run_tests.sh"
EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
    echo ""
    echo "❌  Commit aborted — the fast gate failed."
    echo "    Fix it and commit again. The full gate (semgrep, pip-audit, eslint,"
    echo "    Playwright) runs on push."
    echo ""
    exit 1
fi

echo ""
echo "✅  Fast gate passed — committing."
echo ""
exit 0
HOOK

cat > "$HOOKS/pre-push" <<'HOOK'
#!/usr/bin/env bash
# Installed by scripts/install_git_hooks.sh — edit there, not here, or the change is lost.
REPO_ROOT="$(git rev-parse --show-toplevel)"
REMOTE_NAME="$1"

RED='\033[0;31m'; YELLOW='\033[1;33m'; GREEN='\033[0;32m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

TARGET_BRANCH=""
while IFS=' ' read -r _local_ref _local_sha remote_ref _remote_sha; do
    TARGET_BRANCH="${remote_ref#refs/heads/}"
done

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║         Cloud_IOT — Pre-Push Quality Gate           ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
[ -n "$TARGET_BRANCH" ] && echo -e "  Target branch: ${BOLD}${TARGET_BRANCH}${NC}" && echo ""

# ── main is releases only, and needs an explicit confirmation ──
if [[ "$TARGET_BRANCH" == "main" ]]; then
    echo -e "${YELLOW}${BOLD}  ⚠️  You are pushing to MAIN (release branch).${NC}"
    echo ""
    if git fetch origin develop --quiet 2>/dev/null; then
        DEVELOP_HEAD=$(git rev-parse origin/develop 2>/dev/null || echo "")
        if [ -n "$DEVELOP_HEAD" ] && ! git merge-base --is-ancestor "$DEVELOP_HEAD" "$(git rev-parse HEAD)" 2>/dev/null; then
            echo -e "${RED}  ✘  origin/develop has commits not yet in main.${NC}"
            echo "     Merge develop first: git merge origin/develop"
            echo ""
        else
            echo -e "${GREEN}  ✔  develop is fully merged into main.${NC}"
            echo ""
        fi
    fi
    if [[ "${CLOUD_IOT_RELEASE:-}" == "1" ]]; then
        echo -e "${GREEN}  ✔  Release confirmed via CLOUD_IOT_RELEASE=1${NC}"
        echo ""
    elif read -r -p "  Type 'release' to confirm this is an intentional release: " CONFIRM < /dev/tty 2>/dev/null; then
        echo ""
        if [[ "$CONFIRM" != "release" ]]; then
            echo -e "${RED}❌  Push to main cancelled.${NC}"
            exit 1
        fi
    else
        echo -e "${YELLOW}  No interactive terminal. Set CLOUD_IOT_RELEASE=1.${NC}"
        exit 1
    fi
fi

if [[ "$TARGET_BRANCH" != "main" && "$TARGET_BRANCH" != "develop" && -n "$TARGET_BRANCH" ]]; then
    echo -e "${YELLOW}  ℹ  Feature branch '${TARGET_BRANCH}' — full gate runs on develop/main only.${NC}"
    echo ""
    exit 0
fi

echo -e "${CYAN}${BOLD}[1/2] Full gate (adds semgrep, pip-audit, eslint)...${NC}"
echo ""
GATE_LEVEL=full bash "$REPO_ROOT/tests/run_tests.sh"
if [ $? -ne 0 ]; then
    echo ""
    echo -e "${RED}❌  Push aborted — the full gate failed.${NC}"
    echo ""
    exit 1
fi

echo ""
echo -e "${CYAN}${BOLD}[2/2] Playwright E2E...${NC}"
echo ""
bash "$REPO_ROOT/tests/playwright_e2e.sh"
if [ $? -ne 0 ]; then
    echo ""
    echo -e "${RED}❌  Push aborted — Playwright E2E failed.${NC}"
    echo "    Emergency bypass: git push --no-verify"
    echo ""
    exit 1
fi

echo ""
echo -e "${GREEN}${BOLD}✅  All checks passed — pushing to ${TARGET_BRANCH:-${REMOTE_NAME}}.${NC}"
echo ""
exit 0
HOOK

chmod +x "$HOOKS/pre-commit" "$HOOKS/pre-push" 2>/dev/null || true

echo "Installed:"
echo "  $HOOKS/pre-commit   (GATE_LEVEL=fast)"
echo "  $HOOKS/pre-push     (GATE_LEVEL=full + Playwright)"
echo ""
echo "Verify with:  GATE_LEVEL=fast bash tests/run_tests.sh -q"
