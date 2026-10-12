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


# ── 2026-10-12: a pip failure STOPS the upgrade ───────────────────────────────
#
# The dependency install read
#     [ -f "$VENV_PIP" ] && "$VENV_PIP" install ... | tee ... || warn "pip install had errors"
# so a failed install only warned and the script went on to copy new code onto the old
# dependencies, restart, and report success; a missing pip took the same branch. These run the
# REAL block out of the file with a fake pip, and a marker after the block shows whether the
# upgrade carried on.
#
# NEGATIVE CONTROL — the two refusal tests must FAIL against the previous script:
#     git show f591426:nuc_image/upgrade.sh > /tmp/old.sh
#     UPGRADE_SH_PATH=/tmp/old.sh pytest tests/backend/test_upgrade_script_deps.py -k pip_
# (run 2026-10-12: both failed — the old block reached the marker with exit 0.)

def _helpers(src: str) -> str:
    """The script's own info/warn/error, verbatim (error() is what makes a failure fatal)."""
    return "\n".join(l for l in src.splitlines()
                     if re.match(r"^(info|warn|error)\(\)\s*\{", l))


def _pip_block(src: str) -> str:
    """The `if $DEPS_UNKNOWN || ... requirements.txt` install block, verbatim, to its `fi`."""
    lines = src.splitlines()
    i = next(k for k, l in enumerate(lines) if 'grep -q "^backend/requirements.txt"' in l)
    j = next(k for k in range(i, len(lines)) if lines[k].strip() == "fi")
    return "\n".join(lines[i:j + 1])


def _run_pip_block(tmp_path, pip_body: str | None) -> subprocess.CompletedProcess:
    app = tmp_path / "app"
    (app / "backend" / ".venv" / "bin").mkdir(parents=True)
    if pip_body is not None:
        pip = app / "backend" / ".venv" / "bin" / "pip"
        pip.write_text("#!/bin/bash\n" + pip_body + "\n", newline="\n")
        pip.chmod(0o755)
    src = _script()
    body = f"""
set -euo pipefail
RED=; GREEN=; YELLOW=; CYAN=; BOLD=; NC=
LOG_FILE="{(tmp_path / 'upgrade.log').as_posix()}"
APP_DIR="{app.as_posix()}"
REPO_DIR="{tmp_path.as_posix()}"
DEPS_UNKNOWN=true
CHANGED_FILES=""
{_helpers(src)}
{_pip_block(src)}
echo REACHED_THE_CODE_COPY
"""
    return _run(body)


def test_pip_failure_stops_the_upgrade(tmp_path):
    r = _run_pip_block(tmp_path, 'echo "ERROR: No matching distribution" >&2; exit 1')
    assert "REACHED_THE_CODE_COPY" not in r.stdout, (
        "a failed pip install did not stop the upgrade — new code would be copied onto the "
        f"old dependencies:\n{r.stdout}\n{r.stderr}")
    assert r.returncode != 0
    assert "pip install FAILED" in r.stdout


def test_pip_missing_stops_the_upgrade(tmp_path):
    r = _run_pip_block(tmp_path, None)
    assert "REACHED_THE_CODE_COPY" not in r.stdout, (
        f"a venv with no pip was treated as installed:\n{r.stdout}\n{r.stderr}")
    assert r.returncode != 0
    assert "No pip at" in r.stdout


def test_pip_success_carries_on(tmp_path):
    """Positive control: the refusals above are about failure, not about pip being called."""
    r = _run_pip_block(tmp_path, "exit 0")
    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "REACHED_THE_CODE_COPY" in r.stdout


# ── 2026-10-12: the backend binds loopback, and every upgrade proves it ────────
#
# The unit ran uvicorn --host 0.0.0.0: :8000 answered on the cabinet LAN and the Tailnet,
# around nginx. upgrade.sh never rewrote the unit, so changing the installers alone would have
# left cabinet 1 unchanged. These run the REAL blocks with `systemctl` and `ss` stubbed.

def _bind_block(src: str) -> str:
    start = src.index('BACKEND_UNIT="$(systemctl show -p FragmentPath')
    end = src.index("if $BACKEND_CHANGED; then", start)
    return src[start:end]


def _listen_check(src: str) -> str:
    start = src.index('phase "Checking the backend listens on loopback only"')
    end = src.index("# ── Summary", start)
    return src[start:end]


def _run_bind(tmp_path, unit_text: str) -> tuple[subprocess.CompletedProcess, str]:
    unit = tmp_path / "cloud-iot-backend.service"
    unit.write_text(unit_text, newline="\n")
    calls = tmp_path / "systemctl.calls"
    src = _script()
    body = f"""
set -euo pipefail
RED=; GREEN=; YELLOW=; CYAN=; BOLD=; NC=
LOG_FILE="{(tmp_path / 'upgrade.log').as_posix()}"
{_helpers(src)}
phase() {{ echo "PHASE $*"; }}
systemctl() {{
  echo "$*" >> "{calls.as_posix()}"
  if [ "$1" = show ]; then echo "{unit.as_posix()}"; fi
}}
BACKEND_CHANGED=false
{_bind_block(src)}
echo "BACKEND_CHANGED=$BACKEND_CHANGED"
"""
    r = _run(body)
    return r, (calls.read_text() if calls.exists() else "")


def test_bind_rewrites_a_unit_on_all_interfaces(tmp_path):
    r, calls = _run_bind(tmp_path, "[Service]\nExecStart=/v/bin/uvicorn app.main:app "
                                   "--host 0.0.0.0 --port 8000 --workers 1\n")
    assert r.returncode == 0, r.stderr
    unit = (tmp_path / "cloud-iot-backend.service").read_text()
    assert "--host 127.0.0.1 --port 8000" in unit and "0.0.0.0" not in unit
    assert "daemon-reload" in calls, "the unit changed but systemd was not told"
    assert "BACKEND_CHANGED=true" in r.stdout, "the rebind would not restart the backend"


def test_bind_leaves_a_loopback_unit_alone(tmp_path):
    text = "[Service]\nExecStart=/v/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000\n"
    r, calls = _run_bind(tmp_path, text)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "cloud-iot-backend.service").read_text() == text
    assert "daemon-reload" not in calls and "BACKEND_CHANGED=false" in r.stdout


@pytest.mark.parametrize("ss_out,ok", [
    ("127.0.0.1:8000", True),
    ("0.0.0.0:8000", False),
    ("127.0.0.1:8000\n[::]:8000", False),
    ("", True),            # nothing listening: warned, not failed — the start check covers it
])
def test_every_upgrade_checks_the_bind(tmp_path, ss_out, ok):
    src = _script()
    rows = "\n".join(f"LISTEN 0 2048 {a} 0.0.0.0:*" for a in ss_out.split("\n") if a)
    body = f"""
set -euo pipefail
RED=; GREEN=; YELLOW=; CYAN=; BOLD=; NC=
LOG_FILE="{(tmp_path / 'upgrade.log').as_posix()}"
{_helpers(src)}
phase() {{ echo "PHASE $*"; }}
ss() {{ printf "{rows}\n" | sed '/^$/d'; }}
{_listen_check(src)}
echo PASSED_THE_CHECK
"""
    r = _run(body)
    if ok:
        assert r.returncode == 0 and "PASSED_THE_CHECK" in r.stdout, f"{r.stdout}\n{r.stderr}"
    else:
        assert r.returncode != 0 and "PASSED_THE_CHECK" not in r.stdout, (
            f"a non-loopback listener on :8000 passed the upgrade:\n{r.stdout}")
        assert "non-loopback" in r.stdout
