"""upgrade.sh — the dependency-install guards must work on BOTH deploy paths.

WHY THIS TEST EXISTS
--------------------
`nuc_image/upgrade.sh` reaches the deploy by two routes:

  NEEDS_PULL  — new commits exist, so `git diff HEAD..origin/BRANCH` names the changed files.
  NEEDS_SYNC  — git is already current (someone pulled by hand) but /opt is stale. There is
                no commit range, so the changed set cannot be computed.

`CHANGED_FILES` was assigned only on the first route while being READ on both — at the
npm-install guard and the pip-install guard. Under `set -euo pipefail` those reads failed
with "unbound variable", and because they sit inside `if` conditions bash printed the error
and then evaluated the condition as FALSE instead of aborting. So on the sync-only route
**both dependency installs were silently skipped while the upgrade reported success.**

That shape survived from at least 773bca6 to 282cea5 because nothing ever took the
sync-only route: it requires a manual `git pull` before the script, which nobody did until
the 2026-10-10 cabinet recovery — where it fired twice, at lines 271 and 292.

A grep-only test would pass against a file that defaults CHANGED_FILES to "" and nothing
else, which converts a loud error into a quiet wrong answer ("no files changed" is not true
on that route, it is the absence of a truth). So the test below EXECUTES the real decision
block out of the real file, on the real route, and asserts the installs are selected.
"""
import io
import os
import re
import shutil
import subprocess

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

# Overridable so the suite can be pointed at an older copy of the script as a NEGATIVE
# CONTROL — a test that has never been seen to fail is not evidence. Run:
#
#   git show 773bca6:nuc_image/upgrade.sh > /tmp/old.sh
#   UPGRADE_SH_PATH=/tmp/old.sh pytest tests/backend/test_upgrade_script_deps.py
#
# and the sync-only tests must FAIL with "unbound variable". Unset, it tests the repo's
# own script, which is what the gate runs.
UPGRADE_SH = os.environ.get(
    "UPGRADE_SH_PATH", os.path.join(REPO_ROOT, "nuc_image", "upgrade.sh")
)

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None, reason="bash not available on this host"
)


def _script() -> str:
    return io.open(UPGRADE_SH, encoding="utf-8", newline="").read().replace("\r\n", "\n")


def _decision_block(src: str) -> str:
    """The real changed-file decision, lifted verbatim from upgrade.sh.

    Anchored on the variable initialisations through the end of the if/elif — if that block
    is restructured this raises instead of silently testing nothing.
    """
    start = src.index("BACKEND_CHANGED=false")
    end = src.index("echo -e \"  ${BOLD}Changes detected:${NC}\"")
    block = src[start:end]
    assert "NEEDS_PULL" in block and "NEEDS_SYNC" in block, (
        "the extracted block no longer contains both deploy routes — re-anchor this test"
    )
    return block


def _guard_lines(src: str) -> tuple[str, str]:
    """The two dependency guards, verbatim."""
    npm = next(l for l in src.splitlines() if "grep -q \"^frontend/package\"" in l)
    pip = next(l for l in src.splitlines() if "grep -q \"^backend/requirements.txt\"" in l)
    return npm.strip(), pip.strip()


# Windows process-creation failures. These mean bash NEVER STARTED, so the run says
# nothing about upgrade.sh either way.
#
#   0xC0000142 STATUS_DLL_INIT_FAILED  — the usual symptom of desktop-heap/handle
#                                        exhaustion when a suite spawns many processes
#   0xC0000017 STATUS_NO_MEMORY
#
# Seen on 2026-10-10: the full fast gate hit 0xC0000142 on thirteen tests at once —
# ffmpeg in the guard clip tests, the guard worker subprocesses, and these. Every one of
# them passed when run on its own. A suite that spawns ffmpeg and a worker fleet exhausts
# the resource, and whatever spawns next inherits the failure.
_SPAWN_FAILED = {3221225794, 3221225495}


def _run(body: str) -> subprocess.CompletedProcess:
    """Run a bash fragment, or SKIP if the OS refused to start bash at all.

    WHY SKIP AND NOT FAIL. "Could not run the check" is neither a pass nor a failure, and
    reporting it as either is a lie. Failing would blame upgrade.sh for the host running
    out of handles; passing would claim a verification that never happened.

    The discriminator is narrow on purpose: an exit code from that set AND no output on
    either stream. A bash that actually ran and failed writes to stderr — that is how the
    negative control against 773bca6 produces "CHANGED_FILES: unbound variable". So a real
    defect can never be swallowed by this branch.
    """
    try:
        r = subprocess.run(
            ["bash", "-c", body],
            capture_output=True, text=True, timeout=30,
        )
    except OSError as e:
        pytest.skip(f"could not spawn bash on this host: {e}")
    if r.returncode in _SPAWN_FAILED and not r.stdout and not r.stderr:
        pytest.skip(
            f"bash did not start (exit {r.returncode} = "
            f"0x{r.returncode & 0xFFFFFFFF:08X}, no output on either stream). "
            f"Host resource failure, not a result for upgrade.sh — "
            f"run this file on its own to get a verdict."
        )
    return r


# ── The real defect, on the real route ────────────────────────────────────────

def test_sync_only_route_does_not_hit_unbound_variable():
    """The exact failure seen on the cabinet: 'CHANGED_FILES: unbound variable'."""
    src = _script()
    npm_guard, pip_guard = _guard_lines(src)

    body = f"""
set -euo pipefail
NEEDS_PULL=false
NEEDS_SYNC=true
{_decision_block(src)}
# Reach both guards exactly as the script does. `true` bodies: we are testing selection,
# not the installs themselves.
if {npm_guard.removeprefix('if ').removesuffix('; then')}; then echo NPM_SELECTED; fi
if {pip_guard.removeprefix('if ').removesuffix('; then')}; then echo PIP_SELECTED; fi
"""
    r = _run(body)
    assert "unbound variable" not in r.stderr, (
        f"the sync-only route still reads an unset variable:\n{r.stderr}"
    )
    assert r.returncode == 0, f"block failed: rc={r.returncode}\n{r.stderr}"


def test_sync_only_route_selects_both_dependency_installs():
    """On the route where the changed set is unknowable, BOTH installs must be chosen.

    Running an unnecessary install costs a minute. Skipping a necessary one ships a backend
    that starts `active` and fails later on a lazily-imported package.
    """
    src = _script()
    npm_guard, pip_guard = _guard_lines(src)

    body = f"""
set -euo pipefail
NEEDS_PULL=false
NEEDS_SYNC=true
{_decision_block(src)}
if {npm_guard.removeprefix('if ').removesuffix('; then')}; then echo NPM_SELECTED; fi
if {pip_guard.removeprefix('if ').removesuffix('; then')}; then echo PIP_SELECTED; fi
"""
    # node_modules must NOT exist in the cwd, or the npm guard passes for the wrong reason.
    r = _run(f"cd \"$(mktemp -d)\"\n{body}")
    assert "NPM_SELECTED" in r.stdout, (
        f"npm install not selected on the sync-only route.\nstdout={r.stdout}\nstderr={r.stderr}"
    )
    assert "PIP_SELECTED" in r.stdout, (
        f"pip install not selected on the sync-only route — this is the bug that shipped.\n"
        f"stdout={r.stdout}\nstderr={r.stderr}"
    )


def test_npm_guard_not_satisfied_merely_by_missing_node_modules():
    """`[ ! -d node_modules ]` must not be what rescues the sync-only route.

    With node_modules PRESENT the npm guard has to still fire, otherwise the fix only works
    on a cabinet that has never built the frontend — which is no cabinet in production.
    """
    src = _script()
    npm_guard, _ = _guard_lines(src)
    body = f"""
set -euo pipefail
cd "$(mktemp -d)"
mkdir node_modules
NEEDS_PULL=false
NEEDS_SYNC=true
{_decision_block(src)}
if {npm_guard.removeprefix('if ').removesuffix('; then')}; then echo NPM_SELECTED; fi
"""
    r = _run(body)
    assert "NPM_SELECTED" in r.stdout, (
        "with node_modules present the sync-only route skips npm install again"
    )


# ── The pull route must keep its precision ────────────────────────────────────

def test_pull_route_still_uses_the_real_diff():
    """The fix must not make every upgrade install everything.

    On the NEEDS_PULL route the changed set IS knowable, so a run whose diff touches neither
    package.json nor requirements.txt must select neither install.
    """
    src = _script()
    npm_guard, pip_guard = _guard_lines(src)

    block = _decision_block(src)
    # Replace the real git call with a fixed file list: a backend-only change that leaves
    # dependencies alone.
    block = re.sub(
        r'CHANGED_FILES=\$\(git diff [^)]*\)',
        'CHANGED_FILES="backend/app/routers/controls.py"',
        block,
    )
    assert "git diff" not in block, "failed to stub the git call — test would hit the network"

    body = f"""
set -euo pipefail
cd "$(mktemp -d)"
mkdir node_modules
NEEDS_PULL=true
NEEDS_SYNC=false
{block}
if {npm_guard.removeprefix('if ').removesuffix('; then')}; then echo NPM_SELECTED; fi
if {pip_guard.removeprefix('if ').removesuffix('; then')}; then echo PIP_SELECTED; fi
echo "BACKEND=$BACKEND_CHANGED FRONTEND=$FRONTEND_CHANGED"
"""
    r = _run(body)
    assert r.returncode == 0, r.stderr
    assert "NPM_SELECTED" not in r.stdout, "pull route now installs npm deps unconditionally"
    assert "PIP_SELECTED" not in r.stdout, "pull route now installs pip deps unconditionally"
    assert "BACKEND=true" in r.stdout, "a backend/ change must still flag the backend"
    assert "FRONTEND=false" in r.stdout, "a backend-only change must not flag the frontend"


def test_pull_route_selects_pip_when_requirements_changed():
    src = _script()
    _, pip_guard = _guard_lines(src)
    block = re.sub(
        r'CHANGED_FILES=\$\(git diff [^)]*\)',
        'CHANGED_FILES="backend/requirements.txt"',
        _decision_block(src),
    )
    body = f"""
set -euo pipefail
NEEDS_PULL=true
NEEDS_SYNC=false
{block}
if {pip_guard.removeprefix('if ').removesuffix('; then')}; then echo PIP_SELECTED; fi
"""
    r = _run(body)
    assert "PIP_SELECTED" in r.stdout, r.stderr


# ── Structural guards, so the shape cannot regress quietly ────────────────────

def test_changed_files_is_initialised_before_any_read():
    """No read of CHANGED_FILES may precede its initialisation."""
    src = _script()
    init = src.index('CHANGED_FILES=""')
    first_read = min(
        m.start() for m in re.finditer(r'"\$CHANGED_FILES"', src)
    )
    assert init < first_read, (
        "CHANGED_FILES is read before it is given a default — the unbound-variable bug is back"
    )


def test_deps_unknown_is_set_on_the_sync_only_branch_and_read_by_both_guards():
    src = _script()
    assert "DEPS_UNKNOWN=false" in src, "DEPS_UNKNOWN lost its default"
    assert "DEPS_UNKNOWN=true" in src, "nothing marks the changed set as unknowable any more"
    npm_guard, pip_guard = _guard_lines(src)
    assert "$DEPS_UNKNOWN" in npm_guard, f"npm guard ignores DEPS_UNKNOWN: {npm_guard}"
    assert "$DEPS_UNKNOWN" in pip_guard, f"pip guard ignores DEPS_UNKNOWN: {pip_guard}"


def test_upgrade_script_still_parses():
    r = _run(f'bash -n "{UPGRADE_SH}"')
    assert r.returncode == 0, f"upgrade.sh no longer parses:\n{r.stderr}"
