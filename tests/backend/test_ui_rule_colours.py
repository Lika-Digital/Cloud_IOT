"""TC-UIR-01 — no raw status colour in the marina profile, outside the one component that owns it.
TC-UIR-09 — no marina component over 250 lines (§9), added 2026-10-15 with the block 4 splits.
TC-UIR-10 — the marina profile as a whole stays within 2 752 lines (§9, owner 2026-10-15; raised
2026-10-16 for the guard UI).
(Committed as TC-UIR-02/03, ids the spec and marina.spec.ts already used; renamed 2026-10-16.)

docs/ui_v2_spec.md §4: status is colour + icon + word, all three, always, and the enforcement is
a TEST, not a lint rule (the gate's eslint never ran — D13). Until 2026-10-12 this test was
claimed in a comment (`Status.tsx:12`) and did not exist.

THE RULE, exactly: in `frontend/src/pages/marina/**` and `frontend/src/components/marina/**`, no
class matching RAW below — a status hue on a colour utility. The palette lives in ONE file,
`components/marina/Status.tsx`, which exports named tones; pages use those. Neutral chrome
(gray, blue, white) is not status and is not matched.

EXEMPTIONS, per file, with a deadline that can fail (owner, 2026-10-12): the files block 4
rewrites anyway. The gate fails
  - if a file NOT on the list has a raw colour (so leaving the list means being clean),
  - if a file ON the list has none left (the list must shrink when the file is fixed),
  - if §0.2 of the spec marks block 4 DONE while the list is not empty — without that, "block 4"
    would be a decoration, not a deadline.

FAILS on the code before this change (shown 2026-10-12): MarinaGuard, MarinaAlarms, MarinaWater.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "frontend" / "src"
SCOPE = [SRC / "pages" / "marina", SRC / "components" / "marina"]
PALETTE = SRC / "components" / "marina" / "Status.tsx"
SPEC = ROOT / "docs" / "ui_v2_spec.md"

RAW = re.compile(
    r"\b(?:bg|text|border|ring|fill|stroke|from|to|via|outline|divide|accent|decoration)-"
    r"(?:red|green|amber|yellow|orange|emerald|lime|rose)-\d{2,3}\b")

# Block 4 rewrote these files (row controls, PhaseBlock, wizard step 3, the §9 splits). EMPTY
# since 2026-10-15: MarinaDashboard, BerthDetail and MarinaSetup were split under 250 lines and
# their status colours moved to Status.tsx's TONE. Kept, empty, because TC-UIR-01c reads it.
EXEMPT_UNTIL_BLOCK_4: dict[str, str] = {}

# §9: no marina component over 250 lines (owner, 2026-10-12: "the limit stays").
MAX_LINES = 250
# §9, the whole profile (pages/marina + components/marina, .ts and .tsx). Owner, 2026-10-15: the
# old target "under 1 200" is replaced by the measured size with block 4 complete. Raising it is
# the owner's decision, made in the spec, not by editing this number to get a green gate.
# 2026-10-16, owner: raised to 2 752 with the guard UI — "a measure of movement, not a budget";
# nothing was cut. The rule stands: raised only by the owner, in the spec.
MAX_TOTAL_LINES = 2752


def _files():
    for d in SCOPE:
        yield from sorted(p for p in d.rglob("*.tsx"))


def _raw_lines(p: Path) -> list[str]:
    return [f"{p.relative_to(SRC).as_posix()}:{i}: {m.group(0)}"
            for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
            for m in [RAW.search(line)] if m]


def test_tc_uir_01_no_raw_status_colour_outside_the_palette():
    seen = list(_files())
    assert len(seen) >= 8, f"the scan saw only {len(seen)} files — it is not looking"
    bad = []
    for p in seen:
        rel = p.relative_to(SRC).as_posix()
        if p == PALETTE or rel in EXEMPT_UNTIL_BLOCK_4:
            continue
        bad += _raw_lines(p)
    assert not bad, ("Raw status colour outside components/marina/Status.tsx — use its exported "
                     "tones:\n  " + "\n  ".join(bad))


def test_tc_uir_01b_an_exemption_is_removed_when_its_file_is_clean():
    stale = [f for f in EXEMPT_UNTIL_BLOCK_4
             if (SRC / f).exists() and not _raw_lines(SRC / f)]
    gone = [f for f in EXEMPT_UNTIL_BLOCK_4 if not (SRC / f).exists()]
    assert not stale, f"clean now — remove from EXEMPT_UNTIL_BLOCK_4: {stale}"
    assert not gone, f"no longer exists — remove from EXEMPT_UNTIL_BLOCK_4: {gone}"


def test_tc_uir_01c_block_4_done_means_no_exemptions():
    rows = [l for l in SPEC.read_text(encoding="utf-8").splitlines()
            if l.startswith("| Block 4 — UI v2 remainder |")]
    assert len(rows) == 1, ("the §0.2 status row '| Block 4 — UI v2 remainder |' is missing — it is "
                            "the deadline of EXEMPT_UNTIL_BLOCK_4 and must not disappear")
    state = rows[0].split("|")[2].strip().upper()
    if state.startswith("DONE"):
        assert not EXEMPT_UNTIL_BLOCK_4, (
            f"block 4 is marked {state!r} but files are still exempt: {sorted(EXEMPT_UNTIL_BLOCK_4)}")


def test_tc_uir_09_no_marina_component_over_250_lines():
    """§9 — the limit existed only as a sentence in the spec until 2026-10-15.

    FAILS on the code before the splits (shown 2026-10-15): MarinaDashboard 402, MarinaSetup 307,
    BerthDetail 264. The profile total is TC-UIR-10."""
    seen = list(_files())
    assert len(seen) >= 8, f"the scan saw only {len(seen)} files — it is not looking"
    over = {p.relative_to(SRC).as_posix(): n for p in seen
            if (n := len(p.read_text(encoding="utf-8").splitlines())) > MAX_LINES}
    assert not over, f"over {MAX_LINES} lines (§9): {over}"


def test_tc_uir_10_the_marina_profile_stays_within_its_total():
    """§9 total, owner 2026-10-15: the size with block 4 complete, 2 507 lines. Counts .ts and .tsx, so a hook moved out of a
    component still counts. The scan must see the files it is limiting (not a vacuous zero)."""
    files = [p for d in SCOPE for p in sorted(d.rglob("*.ts*")) if p.suffix in (".ts", ".tsx")]
    assert len(files) >= 20, f"the scan saw only {len(files)} files — it is not looking"
    total = sum(len(p.read_text(encoding="utf-8").splitlines()) for p in files)
    assert total <= MAX_TOTAL_LINES, (
        f"the marina profile is {total} lines, over the §9 limit of {MAX_TOTAL_LINES} — "
        f"the limit is the owner's to change (docs/ui_v2_spec.md §0.2), not this test's")
