#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  Wire this clone up to the tracked git hooks.
#
#      bash scripts/install_git_hooks.sh
#
#  It sets ONE config value: core.hooksPath = .githooks
#
#  WHY IT IS ONE LINE NOW. The first version of this script copied hook bodies into
#  .git/hooks/, which is untracked — so every gate improvement lived on one machine and a
#  fresh clone had no gate at all while looking exactly like a clone that passed. That is the
#  same shape as an E2E stage exiting 0 with nothing running: a green signal with nothing
#  behind it.
#
#  `core.hooksPath` points git at a TRACKED directory instead, so hook content now travels
#  with the repository and an improvement reaches everyone on their next pull. The only
#  per-clone step left is this one config line.
#
#  WHAT STILL CANNOT BE ENFORCED, stated rather than glossed over. There is no CI in this
#  repository, so nothing external can notice a clone that never ran this script. The cheapest
#  enforcement available is a test — tests/backend/test_git_hooks_wired.py fails, with the fix
#  command in the message, whenever the suite runs in a worktree whose hooks are not wired up.
#  That catches anyone who runs the tests at all. It does NOT catch someone who never runs
#  tests and never runs this script; such a person commits with no gate, and without CI no
#  repository-side mechanism can prevent that. Accepted knowingly.
#
#  THE GATE SPLIT (v3.43)
#    pre-commit -> GATE_LEVEL=fast : pytest + bandit + gap checks. ~4.5 min, bounded.
#    pre-push   -> GATE_LEVEL=full : adds semgrep, pip-audit, ESLint, then Playwright.
#
#  The split came from a measurement, not a preference: pip-audit fetches PyPI's advisory
#  database and ran >122 s without completing. Its result was already advisory while its
#  runtime was unbounded — and a non-blocking check that can hang forever still blocks.
#  Do not fold pip-audit back into the commit path.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [ ! -e .git ]; then
    echo "Not a git working tree: $ROOT" >&2
    exit 1
fi

if [ ! -d .githooks ]; then
    echo "Missing .githooks/ — expected tracked hooks in the repository." >&2
    exit 1
fi

git config core.hooksPath .githooks
chmod +x .githooks/* 2>/dev/null || true

echo "core.hooksPath = $(git config --get core.hooksPath)"
echo ""
echo "Hooks now come from the tracked .githooks/ directory:"
echo "  pre-commit  GATE_LEVEL=fast   (pytest + bandit + gap checks)"
echo "  pre-push    GATE_LEVEL=full   (+ semgrep, pip-audit, eslint, Playwright)"
echo ""
echo "Verify:  GATE_LEVEL=fast bash tests/run_tests.sh -q"
