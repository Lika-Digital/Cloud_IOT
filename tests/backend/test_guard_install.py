"""Guard INSTALL step — nuc_image/install-guard.sh and cloud-iot-guard.service (2026-10-13).

The REAL script runs, under bash, in a temp root (GUARD_INSTALL_ROOT). The system commands it
calls (useradd, chown, systemctl, python3 -m venv, pip) are stubs that LOG their calls, so the
test can say what the script did and — the point of half of these — what it did NOT do.

  TC-GINS-01  a fresh install with the model present: exit 0, everything in place
  TC-GINS-02  INSTALL IS NOT START: systemctl is only ever asked to daemon-reload
  TC-GINS-03  idempotent: a second run changes no file, installs nothing, exits 0
  TC-GINS-04  negative control — model missing: exit 3, says so, never says installed/ready
  TC-GINS-05  the camera URL (it carries the password) is never printed or logged
  TC-GINS-06  openvino importable from the BACKEND venv → the install fails, loudly
  TC-GINS-07  one instance id, the same in guard.env and the backend .env; a mismatch fails
  TC-GINS-08  a failing pip is a failure, not a warning
  TC-GINS-09  the unit: never enabled by the script, egress filter as measured, own venv
  TC-GINS-10  openvino-telemetry (installed BY pip as openvino's dependency) is removed when
              the smoke test passes without it — TELEMETRY: REMOVED
  TC-GINS-11  ...and put back, loudly, when the smoke test needs it — TELEMETRY: KEPT, exit 0
  TC-GINS-12  negative control — a smoke test that fails even with it back: exit 1, never
              "installed", and the package is back (openvino is not left without it)
  TC-GINS-13  no model: nothing can prove openvino works without it, so it is not touched
  TC-GINS-14  one copy, one path (owner, 2026-10-15): the exporter, guard.env and the worker's
              default all name /opt/cloud-iot/backend/models; no guard/models is made
  TC-GINS-15  readiness looks where the WORKER will: a kept guard.env pointing elsewhere is
              MODEL MISSING and says so, and correcting that one line makes it ready
  TC-GINS-16  negative control — a model the guard account cannot read is NOT ready (exit 3)

What this cannot show, and §13 does: that the real openvino wheel installs on the NUC's
Python, that useradd/chown behave, and that the worker really starts under the unit.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "nuc_image" / "install-guard.sh"
SMOKE = REPO / "nuc_image" / "guard_smoke.py"
UNIT = REPO / "nuc_image" / "cloud-iot-guard.service"
SECRET_URL = "rtsp://admin:Pa55-word-9@192.168.1.191:554/profile1"


def _bash() -> str | None:
    """Git's bash on Windows — NOT System32\\bash.exe, which is the WSL launcher."""
    override = os.environ.get("GUARD_TEST_BASH")
    if override:
        return override
    if os.name != "nt":
        return shutil.which("bash")
    found = shutil.which("bash")
    if found and "system32" not in found.lower():
        return found
    git = shutil.which("git")
    if git:
        # git.exe is in Git\cmd, Git\mingw64\bin, or — inside a git hook, which is where the
        # gate runs — Git\mingw64\libexec\git-core. Walk up until Git's own bin\bash.exe.
        # (The first version looked two levels up only, and the gate skipped all nine tests.)
        for root in Path(git).resolve().parents:
            for cand in (root / "bin" / "bash.exe", root / "usr" / "bin" / "bash.exe"):
                if cand.is_file():
                    return str(cand)
    return None


BASH = _bash()
pytestmark = pytest.mark.skipif(
    BASH is None, reason="no bash — the install step is UNTESTED here, not passed")


def _stub(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/usr/bin/env bash\n" + body + "\n", encoding="utf-8", newline="\n")
    path.chmod(0o755)


class Rig:
    def __init__(self, tmp: Path, *, model=True, backend_openvino=False, pip_fails=False,
                 smoke: str | None = None, readable=True):
        self.tmp = tmp
        self.root = tmp / "root"
        self.calls = tmp / "calls.log"
        stubs = tmp / "stubs"
        # The scripts as git stores them (LF): a CRLF checkout on Windows would break bash.
        nuc = tmp / "nuc_image"
        nuc.mkdir(parents=True)
        for src in (SCRIPT, UNIT, SMOKE):
            (nuc / src.name).write_bytes(src.read_bytes().replace(b"\r\n", b"\n"))
        self.script = nuc / SCRIPT.name

        log = f'echo "$(basename "$0") $*" >> "{self.calls.as_posix()}"'
        _stub(stubs / "useradd", f'{log}; touch "{(tmp / "user_exists").as_posix()}"')
        _stub(stubs / "id", f'[ -f "{(tmp / "user_exists").as_posix()}" ]')
        _stub(stubs / "chown", f'{log}; for a; do :; done; [ -d "$a" ] && touch "$a/.owned_by_guard"; exit 0')
        _stub(stubs / "owner_of", '[ -f "$1/.owned_by_guard" ] && echo guard || echo root')
        _stub(stubs / "systemctl", log)
        # `runuser -u guard -- <cmd>`: runs the command, or (readable=False) is refused, as a
        # file the guard account may not open would be.
        _stub(stubs / "runas", 'exec "$@"' if readable else 'exit 1')
        venv_py = f'{log}; exit 0'
        venv_pip = f'{log}; exit {1 if pip_fails else 0}'
        _stub(stubs / "python3", f"""{log}
if [ "$1" = "-m" ] && [ "$2" = "venv" ]; then
  mkdir -p "$3/bin"
  printf '%s\\n' '#!/usr/bin/env bash' '{venv_py}' > "$3/bin/python"
  printf '%s\\n' '#!/usr/bin/env bash' '{venv_pip}' > "$3/bin/pip"
  chmod 755 "$3/bin/python" "$3/bin/pip"
fi""")
        self.env = {**os.environ,
                    "GUARD_INSTALL_ROOT": self.root.as_posix(), "REPO_DIR": REPO.as_posix(),
                    "GUARD_PYTHON": (stubs / "python3").as_posix(),
                    "GUARD_SYSTEMCTL": (stubs / "systemctl").as_posix(),
                    "GUARD_USERADD": (stubs / "useradd").as_posix(),
                    "GUARD_CHOWN": (stubs / "chown").as_posix(),
                    "GUARD_OWNER_OF": (stubs / "owner_of").as_posix(),
                    "GUARD_ID": (stubs / "id").as_posix(),
                    "GUARD_RUNAS": (stubs / "runas").as_posix()}

        app = self.root / "opt" / "cloud-iot"
        (app / "backend" / "app" / "guard").mkdir(parents=True)      # upgrade.sh deployed it
        self.backend_env = app / "backend" / ".env"
        self.backend_env.write_text("JWT_SECRET=x\nMQTT_BROKER_HOST=localhost\n", encoding="utf-8")
        _stub(app / "backend" / ".venv" / "bin" / "python",
              f'{log}; exit {1 if backend_openvino else 0}')
        self.guard_env = app / "guard" / "guard.env"
        self.tele = tmp / "telemetry_installed"
        if smoke is not None:
            # A venv whose pip behaves like the real one around openvino-telemetry: installing
            # the requirements pulls it in (openvino depends on it), uninstall removes it.
            # The smoke test passes always ("ok"), only with the package ("needs"), or never.
            t = self.tele.as_posix()
            ok_if = {"ok": "true", "needs": f'[ -f "{t}" ]', "broken": "false"}[smoke]
            venv_bin = app / "guard" / ".venv" / "bin"
            _stub(venv_bin / "python", f"""{log}
case "$*" in
  *importlib.metadata*) [ -f "{t}" ] && {{ echo 2025.2.0; exit 0; }}; exit 1 ;;
  *guard_smoke.py*) if {ok_if}; then echo "SMOKE OK: stub"; exit 0; fi; echo "SMOKE FAIL: stub"; exit 1 ;;
esac
exit 0""")
            _stub(venv_bin / "pip", f"""{log}
case "$*" in
  *uninstall*openvino-telemetry*) rm -f "{t}" ;;
  *openvino-telemetry==*) touch "{t}" ;;
  *-r*) touch "{t}" ;;
esac
exit 0""")
        if model:
            # Where scripts/guard_export_model.sh writes it, and where it is on cabinet 1
            # (measured 2026-10-15) — the backend's directory.
            ir = app / "backend" / "models" / "yolov8n_openvino"
            ir.mkdir(parents=True)
            (ir / "yolov8n.xml").write_text("<net/>")
            (ir / "yolov8n.bin").write_bytes(b"\0" * 64)

    def run(self) -> subprocess.CompletedProcess:
        return subprocess.run([BASH, self.script.as_posix()], env=self.env, capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=120)

    def calls_of(self, cmd: str) -> list[str]:
        if not self.calls.exists():
            return []
        return [l for l in self.calls.read_text().splitlines() if l.split(" ", 1)[0] == cmd]

    def snapshot(self) -> dict[str, str]:
        return {p.relative_to(self.root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(self.root.rglob("*")) if p.is_file()
                and "var/log" not in p.as_posix()}

    def install_log(self) -> str:
        p = self.root / "var" / "log" / "cloud-iot" / "guard-install.log"
        return p.read_text(encoding="utf-8") if p.exists() else ""


def _env_value(path: Path, key: str) -> str | None:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(key + "="):
            return line.split("=", 1)[1]
    return None


def test_tc_gins_01_fresh_install_puts_everything_in_place(tmp_path):
    rig = Rig(tmp_path)
    r = rig.run()
    assert r.returncode == 0, r.stdout + r.stderr
    app = rig.root / "opt" / "cloud-iot"
    assert (app / "guard_worker" / "__main__.py").is_file(), "worker code not deployed"
    assert (app / "guard" / ".venv" / "bin" / "python").is_file(), "the guard's OWN venv"
    assert (rig.root / "etc/systemd/system/cloud-iot-guard.service").read_bytes() == \
        UNIT.read_bytes().replace(b"\r\n", b"\n")
    assert (rig.root / "var/lib/marina-guard/recordings").is_dir()
    assert any("--only-binary=:all:" in c for c in rig.calls_of("pip")), "wheels only"
    assert rig.calls_of("useradd"), "the guard account was not created"
    assert "GUARD INSTALLED" in r.stdout and "not started" in r.stdout


def test_tc_gins_02_install_is_not_start(tmp_path):
    rig = Rig(tmp_path)
    for _ in range(2):
        assert rig.run().returncode == 0
    verbs = [c.split()[1] for c in rig.calls_of("systemctl")]
    assert verbs == ["daemon-reload"], f"systemctl was asked for more than a reload: {verbs}"


def test_tc_gins_03_a_second_run_changes_nothing(tmp_path):
    rig = Rig(tmp_path)
    assert rig.run().returncode == 0
    before, calls_before = rig.snapshot(), rig.calls.read_text()
    r = rig.run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert rig.snapshot() == before, "the second run changed a file"
    new = rig.calls.read_text()[len(calls_before):].splitlines()
    acted = [c for c in new if c.split(" ", 1)[0] in ("useradd", "pip", "systemctl")
             or c.startswith("python3 -m venv")]
    assert not acted, f"the second run acted: {acted}"
    assert "[+]" not in r.stdout, f"the second run reported a change:\n{r.stdout}"


def test_tc_gins_04_model_missing_is_not_a_success(tmp_path):
    rig = Rig(tmp_path, model=False)
    r = rig.run()
    assert r.returncode == 3, r.stdout + r.stderr
    assert "MODEL MISSING" in r.stdout and "NOT a success" in r.stdout
    assert "GUARD INSTALLED" not in r.stdout, "a missing model was reported as installed"
    # and the model's arrival is what makes it ready — nothing else changes the verdict
    ir = rig.root / "opt/cloud-iot/backend/models/yolov8n_openvino"
    ir.mkdir(parents=True)
    (ir / "m.xml").write_text("<net/>")
    assert rig.run().returncode == 3, "an .xml without its .bin is not a model"
    (ir / "m.bin").write_bytes(b"\0" * 8)
    assert rig.run().returncode == 0


def test_tc_gins_05_the_camera_url_is_never_printed(tmp_path):
    rig = Rig(tmp_path)
    assert rig.run().returncode == 0
    text = rig.guard_env.read_text(encoding="utf-8").replace(
        "GUARD_STREAM_URL=", f"GUARD_STREAM_URL={SECRET_URL}")
    rig.guard_env.write_text(text, encoding="utf-8")
    outs = [rig.run()]
    rig.backend_env.write_text(rig.backend_env.read_text() + "GUARD_INSTANCE_ID=other\n")
    outs.append(rig.run())                                  # an error path, too
    assert outs[1].returncode == 1
    seen = "".join(o.stdout + o.stderr for o in outs) + rig.install_log()
    for piece in ("Pa55-word-9", "admin:", SECRET_URL):
        assert piece not in seen, f"{piece!r} reached the output or the log"
    assert "camera URL: set (rtsp://" in outs[0].stdout, "presence must still be reported"


def test_tc_gins_06_openvino_in_the_backend_venv_fails_the_install(tmp_path):
    rig = Rig(tmp_path, backend_openvino=True)
    r = rig.run()
    assert r.returncode == 1 and "must never be there" in r.stdout, r.stdout
    assert "GUARD INSTALLED" not in r.stdout
    backend_pip = [c for c in rig.calls_of("pip")
                   if "backend" in c]
    assert not backend_pip, "the script ran pip in the backend venv"


def test_tc_gins_07_one_instance_id_on_both_sides(tmp_path):
    rig = Rig(tmp_path)
    assert rig.run().returncode == 0
    g = _env_value(rig.guard_env, "GUARD_INSTANCE_ID")
    b = _env_value(rig.backend_env, "GUARD_INSTANCE_ID")
    assert g and g == b, (g, b)
    assert _env_value(rig.guard_env, "MARINA_ID") == "KRK", "the backend's default marina"
    assert rig.run().returncode == 0
    assert _env_value(rig.guard_env, "GUARD_INSTANCE_ID") == g, "the id must not be regenerated"
    rig.backend_env.write_text(rig.backend_env.read_text().replace(g, "someone-else"))
    r = rig.run()
    assert r.returncode == 1 and "differs" in r.stdout, r.stdout


def test_tc_gins_08_a_failing_pip_is_a_failure(tmp_path):
    rig = Rig(tmp_path, pip_fails=True)
    r = rig.run()
    assert r.returncode == 1 and "FAILED" in r.stdout, r.stdout
    assert "GUARD INSTALLED" not in r.stdout
    assert not (rig.root / "opt/cloud-iot/guard/.venv/.requirements.sha256").exists(), \
        "a failed install must not be stamped as done, or the next run would skip it"


def test_tc_gins_09_the_unit_file(tmp_path):
    unit = UNIT.read_text(encoding="utf-8")
    keys = [l.split("=", 1) for l in unit.splitlines() if "=" in l and not l.startswith("#")]
    kv = {}
    for k, v in keys:
        kv.setdefault(k.strip(), []).append(v.strip())
    assert kv["ExecStart"] == ["/opt/cloud-iot/guard/.venv/bin/python -m guard_worker"]
    assert kv["User"] == ["guard"] and kv["WorkingDirectory"] == ["/opt/cloud-iot"]
    assert kv["IPAddressDeny"] == ["any"]
    allow = kv["IPAddressAllow"][0].split()
    # each entry measured 2026-10-13 — see the unit's comment
    assert set(allow) == {"localhost", "172.18.0.0/16", "192.168.1.0/24"}, allow
    assert kv["ReadWritePaths"] == ["/var/lib/marina-guard"]
    script = SCRIPT.read_text(encoding="utf-8")
    for verb in ("enable", "start", "restart"):
        assert f"$SYSTEMCTL {verb}" not in script and f"systemctl {verb}" not in script.replace(
            "# ", "").split("set -euo pipefail", 1)[1], f"the install script can {verb} the unit"


# ═══ TC-GINS-10..13 — openvino-telemetry, decided by the smoke test (2026-10-15) ═══════════

def test_tc_gins_10_removed_when_openvino_works_without_it(tmp_path):
    rig = Rig(tmp_path, smoke="ok")
    r = rig.run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert "TELEMETRY: REMOVED — openvino-telemetry 2025.2.0 uninstalled" in r.stdout, r.stdout
    assert not rig.tele.exists(), "the package is still installed"
    pip = rig.calls_of("pip")
    assert any("uninstall -y -q openvino-telemetry" in c for c in pip), pip
    assert not any("openvino-telemetry==" in c for c in pip), "reinstalled although not needed"
    # Second run: already absent, the smoke test still runs and still passes.
    r2 = rig.run()
    assert r2.returncode == 0 and "TELEMETRY: REMOVED — openvino-telemetry absent" in r2.stdout, r2.stdout


def test_tc_gins_11_put_back_loudly_when_openvino_needs_it(tmp_path):
    rig = Rig(tmp_path, smoke="needs")
    r = rig.run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert "TELEMETRY: KEPT — openvino needs openvino-telemetry 2025.2.0" in r.stdout, r.stdout
    assert "kernel filter ALONE" in r.stdout
    assert rig.tele.exists(), "openvino was left without a dependency it needs"
    pip = [c for c in rig.calls_of("pip") if "openvino-telemetry" in c]
    assert [("uninstall" in c) for c in pip] == [True, False], pip   # removed, then put back


def test_tc_gins_12_negative_control_a_smoke_test_that_fails_fails_the_install(tmp_path):
    rig = Rig(tmp_path, smoke="broken")
    r = rig.run()
    assert r.returncode == 1, r.stdout + r.stderr
    assert "SMOKE TEST FAILED with openvino-telemetry back in place" in r.stdout, r.stdout
    assert "GUARD INSTALL FAILED" in r.stdout
    assert "GUARD INSTALLED" not in r.stdout and "TELEMETRY: REMOVED" not in r.stdout
    assert rig.tele.exists(), "the package was not put back"


def test_tc_gins_13_no_model_nothing_decided_nothing_removed(tmp_path):
    rig = Rig(tmp_path, model=False, smoke="ok")
    r = rig.run()
    assert r.returncode == 3, r.stdout + r.stderr
    assert "TELEMETRY: NOT DECIDED" in r.stdout, r.stdout
    assert rig.tele.exists()
    assert not any("uninstall" in c for c in rig.calls_of("pip"))


# ═══ TC-GINS-14..16 — the model: one copy, one path (owner, 2026-10-15) ═════════════════

BACKEND_MODELS = "/opt/cloud-iot/backend/models"


def test_tc_gins_14_one_copy_one_path(tmp_path):
    exporter = (REPO / "scripts" / "guard_export_model.sh").read_text(encoding="utf-8")
    assert f'MODELS_DIR="${{MODELS_DIR:-{BACKEND_MODELS}}}"' in exporter, \
        "the exporter no longer writes where the worker reads"
    worker = (REPO / "guard_worker" / "__main__.py").read_text(encoding="utf-8")
    assert f'model_dir: str = "{BACKEND_MODELS}"' in worker, "the worker's default model_dir"
    assert f'_env("GUARD_MODEL_DIR", "{BACKEND_MODELS}")' in worker, "the worker's env default"
    rig = Rig(tmp_path)
    r = rig.run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert _env_value(rig.guard_env, "GUARD_MODEL_DIR") == BACKEND_MODELS
    assert f"GUARD_MODEL_DIR={BACKEND_MODELS} points at it" in r.stdout, r.stdout
    assert not (rig.root / "opt/cloud-iot/guard/models").exists(), \
        "a second model directory was made: two places a model can be, one of them stale"


def test_tc_gins_15_readiness_looks_where_the_worker_will(tmp_path):
    rig = Rig(tmp_path)
    assert rig.run().returncode == 0
    # A guard.env kept from an install before 2026-10-15 still names the old directory.
    text = rig.guard_env.read_text(encoding="utf-8")
    rig.guard_env.write_text(text.replace(f"GUARD_MODEL_DIR={BACKEND_MODELS}",
                                          "GUARD_MODEL_DIR=/opt/cloud-iot/guard/models"),
                             encoding="utf-8")
    r = rig.run()
    assert r.returncode == 3, "the worker would not find the model, yet the install said ready"
    assert "MODEL MISSING" in r.stdout and "guard.env points away from" in r.stdout, r.stdout
    assert "GUARD INSTALLED" not in r.stdout
    rig.guard_env.write_text(text, encoding="utf-8")
    assert rig.run().returncode == 0, "correcting GUARD_MODEL_DIR alone must make it ready"


def test_tc_gins_16_negative_control_unreadable_model_is_not_ready(tmp_path):
    rig = Rig(tmp_path, readable=False)
    r = rig.run()
    assert r.returncode == 3, r.stdout + r.stderr
    assert "MODEL NOT READABLE by 'guard'" in r.stdout, r.stdout
    assert "GUARD INSTALLED" not in r.stdout
