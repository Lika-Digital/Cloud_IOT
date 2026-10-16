"""TC-GATE — which commit gate runs is decided mechanically by tests/gate_path.sh (owner, 2026-10-16).

Only .md files staged -> the docs-only check (the tests that READ .md files); any other file, or
nothing staged -> the full commit gate. No bypass flag. Each case stages real files in a throwaway
git repository and runs the real script, so the test measures git's own file list, not a copy of
the rule. TC-GATE-02 is the owner's negative control: one .md plus one .py goes to the full gate.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tests" / "gate_path.sh"
BASH = shutil.which("bash")
GIT = shutil.which("git")

pytestmark = pytest.mark.skipif(not (BASH and GIT), reason="needs bash and git on PATH")


def _repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    (r / "tests" / "backend").mkdir(parents=True)
    (r / "docs").mkdir()
    for args in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"],
                 ["config", "core.autocrlf", "false"]):
        subprocess.run([GIT, *args], cwd=r, check=True)
    shutil.copy(SCRIPT, r / "tests" / "gate_path.sh")
    # One test that reads a spec, one that does not: the selection must take exactly the first.
    (r / "tests" / "backend" / "test_reads_spec.py").write_text(
        'SPEC = "docs/spec.md"\ndef test_x():\n    assert SPEC\n', encoding="utf-8")
    (r / "tests" / "backend" / "test_plain.py").write_text(
        "def test_y():\n    assert True\n", encoding="utf-8")
    (r / "docs" / "spec.md").write_text("# spec\n", encoding="utf-8")
    (r / "app.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run([GIT, "add", "-A"], cwd=r, check=True)
    subprocess.run([GIT, "commit", "-q", "-m", "base"], cwd=r, check=True)
    return r


def _decide(r: Path) -> dict:
    out = subprocess.run([BASH, "tests/gate_path.sh"], cwd=r, capture_output=True, text=True,
                         check=True).stdout
    return dict(line.split("=", 1) for line in out.splitlines() if "=" in line)


def _stage(r: Path, *paths: str) -> None:
    subprocess.run([GIT, "add", "-A", *paths], cwd=r, check=True)


def test_tc_gate_01_only_md_goes_docs_only_and_selects_the_spec_readers(tmp_path):
    r = _repo(tmp_path)
    (r / "docs" / "spec.md").write_text("# spec\nchanged\n", encoding="utf-8")
    (r / "README.md").write_text("new\n", encoding="utf-8")
    _stage(r)
    d = _decide(r)
    assert d["GATE_PATH"] == "docs", d
    assert "2 changed file(s) are .md" in d["GATE_REASON"], d
    assert d["GATE_DOC_TESTS"] == "tests/backend/test_reads_spec.py", d


def test_tc_gate_02_md_plus_py_goes_to_the_full_gate(tmp_path):
    """The owner's negative control."""
    r = _repo(tmp_path)
    (r / "docs" / "spec.md").write_text("# spec\nchanged\n", encoding="utf-8")
    (r / "app.py").write_text("x = 2\n", encoding="utf-8")
    _stage(r)
    d = _decide(r)
    assert d["GATE_PATH"] == "full", d
    assert "app.py" in d["GATE_REASON"] and "not .md" in d["GATE_REASON"], d
    assert "GATE_DOC_TESTS" not in d


def test_tc_gate_03_nothing_staged_is_not_documentation_only(tmp_path):
    d = _decide(_repo(tmp_path))
    assert d["GATE_PATH"] == "full", d


def test_tc_gate_04_a_rename_from_py_to_md_is_not_documentation(tmp_path):
    r = _repo(tmp_path)
    subprocess.run([GIT, "mv", "app.py", "app.md"], cwd=r, check=True)
    d = _decide(r)
    assert d["GATE_PATH"] == "full", d
    assert "app.py" in d["GATE_REASON"], d


def test_tc_gate_05_lookalike_extensions_are_not_md(tmp_path):
    r = _repo(tmp_path)
    for name in ("notes.MD", "page.mdx", "doc.markdown", "spec.md.bak"):
        (r / name).write_text("x\n", encoding="utf-8")
        _stage(r, name)
        assert _decide(r)["GATE_PATH"] == "full", name
        subprocess.run([GIT, "rm", "-q", "--cached", name], cwd=r, check=True)


def test_tc_gate_06_deleting_code_is_not_documentation(tmp_path):
    r = _repo(tmp_path)
    subprocess.run([GIT, "rm", "-q", "app.py"], cwd=r, check=True)
    assert _decide(r)["GATE_PATH"] == "full"


def test_tc_gate_07_the_real_selection_holds_every_test_that_reads_a_spec():
    """In THIS repository: the docs-only check must include TC-UIR-01c's file (it reads
    docs/ui_v2_spec.md), and every test file that builds a path into docs/ must be selected."""
    import re
    selected = {p.name for p in (ROOT / "tests" / "backend").glob("test_*.py")
                if re.search(r"\.md[\"']", p.read_text(encoding="utf-8"))}
    assert "test_ui_rule_colours.py" in selected, selected
    for p in (ROOT / "tests" / "backend").glob("test_*.py"):
        src = p.read_text(encoding="utf-8")
        if re.search(r"/\s*[\"']docs[\"']", src):
            assert p.name in selected, f"{p.name} builds a path into docs/ but is not selected"
