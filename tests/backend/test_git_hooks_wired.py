"""
Are this clone's git hooks actually wired up? (v3.43)
====================================================

`.git/hooks/` is **untracked**, so for most of this project's life every gate improvement
existed on one machine only — and a fresh clone had no gate at all while looking exactly like a
clone that passed. That is the same shape as an E2E stage exiting 0 with nothing running: a
green signal with nothing behind it.

v3.43 moves the hooks into a tracked `.githooks/` directory and points git at it with
`core.hooksPath`, so hook content now travels with the repository. One per-clone config line
remains, and **this file is the only thing that notices when it was never run.**

There is no CI in this repository, so nothing external can check. This test is therefore the
cheapest enforcement available, and its limit is worth stating: it catches anyone who runs the
suite, and it cannot catch someone who never runs the tests and never runs the installer. Such a
person commits with no gate, and without CI no repository-side mechanism can prevent that.

  TC-HOOK-01  the tracked hooks exist and carry their gate level
  TC-HOOK-02  this clone is wired to them
  TC-HOOK-03  the fast gate is named as fast in its own output
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
GITHOOKS = REPO / ".githooks"

INSTALL_HINT = "Run:  bash scripts/install_git_hooks.sh"


def _is_git_worktree() -> bool:
    return (REPO / ".git").exists()


pytestmark = pytest.mark.skipif(
    not _is_git_worktree(),
    reason="not a git worktree (source export / container build) — hooks are not applicable",
)


def test_tc_hook_01_tracked_hooks_exist_with_their_gate_levels():
    """The hooks must be in the repository, not only in someone's .git directory."""
    pre_commit = GITHOOKS / "pre-commit"
    pre_push = GITHOOKS / "pre-push"

    assert pre_commit.is_file(), f"{pre_commit} is missing. {INSTALL_HINT}"
    assert pre_push.is_file(), f"{pre_push} is missing. {INSTALL_HINT}"

    commit_body = pre_commit.read_text(encoding="utf-8", errors="replace")
    push_body = pre_push.read_text(encoding="utf-8", errors="replace")

    assert "GATE_LEVEL=fast" in commit_body, (
        "the tracked pre-commit hook does not select the fast gate. The split exists because "
        "pip-audit hung for >122 s in the commit path; do not fold it back in."
    )
    assert "GATE_LEVEL=full" in push_body, (
        "the tracked pre-push hook does not select the full gate, so semgrep, pip-audit and "
        "ESLint would never run at all"
    )


def test_tc_hook_02_this_clone_is_wired_to_them():
    """core.hooksPath must point at the tracked directory.

    This is the assertion that catches a clone where nobody ran the installer — the case that
    otherwise commits with no gate and is indistinguishable from a clone that passed.
    """
    result = subprocess.run(
        ["git", "config", "--get", "core.hooksPath"],
        cwd=str(REPO), capture_output=True, text=True,
    )
    configured = result.stdout.strip()

    if configured:
        assert configured.replace("\\", "/").rstrip("/").endswith(".githooks"), (
            f"core.hooksPath is {configured!r}, not the tracked .githooks directory. "
            f"{INSTALL_HINT}"
        )
        return

    # No hooksPath: fall back to checking the legacy location, so a clone set up before v3.43
    # is not reported as ungated when it does in fact have working hooks.
    legacy = REPO / ".git" / "hooks" / "pre-commit"
    assert legacy.is_file() and "GATE_LEVEL" in legacy.read_text(
        encoding="utf-8", errors="replace"), (
        "This clone has no git hooks wired up, so commits are running with NO GATE — no "
        "pytest, no bandit, no gap checks. It looks identical to a clone that passed.\n"
        f"{INSTALL_HINT}"
    )


def test_tc_hook_03_the_fast_gate_names_itself():
    """A commit-time green must not be readable as a full-gate green.

    The fast gate deliberately omits semgrep, pip-audit and ESLint. If its output did not say
    so, "all checks passed" at commit time would be mistaken for the complete set — the same
    confusion as a skipped test reported inside a total.
    """
    runner = (REPO / "tests" / "run_tests.sh").read_text(encoding="utf-8", errors="replace")

    assert "Gate level: ${GATE_LEVEL}" in runner, \
        "the runner does not announce which gate level it is running"
    assert "SKIPPED_STAGES" in runner, \
        "the runner does not track which stages it skipped"
    assert "Stages NOT RUN at gate level" in runner, (
        "the runner does not list what it did not run. A gate is only trustworthy if it "
        "reports its own gaps."
    )
