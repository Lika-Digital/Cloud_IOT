#!/usr/bin/env python3
"""Verify the `scikit-learn>=1.5,<2` range on a machine that HAS scikit-learn.

WHY THIS EXISTS AS A SCRIPT AND NOT A TEST
------------------------------------------
tests/backend/test_prediction_service.py contains
`test_real_sklearn_recovers_a_known_linear_relationship`, which is the only check that can
justify the scikit-learn range in backend/requirements.txt. It skips wherever the library is
absent — which is the whole development box, since scikit-learn publishes no 32-bit Windows
wheel and the dev interpreter is Python 3.13 32-bit.

So the verification was assigned to the cabinet. And the cabinet has no pytest: 58 packages
in the production venv and no test framework among them. A check placed where it cannot run
is a check that gets skipped and read as passed — the same defect this project has been
digging out all week, one layer further out.

This script therefore mirrors that test with no framework at all. It asserts the SAME things
and prints each one with the value it actually got, so the output is the evidence rather than
a bare exit code.

RUN IT:
    /opt/cloud-iot/backend/.venv/bin/python3 scripts/verify_sklearn_range.py

EXIT CODES:
    0  every check passed            -> paste the output; the range is justified
    1  a check failed               -> the range is NOT justified; do not stamp it
    2  scikit-learn is absent       -> on a cabinet this is a FAILURE, not a skip:
                                       prediction_service silently returns nothing
"""
from __future__ import annotations

import os
import struct
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta

MIRRORS = ("tests/backend/test_prediction_service.py::"
           "test_real_sklearn_recovers_a_known_linear_relationship")

# ── Make `app.*` importable from either the repo or the deployed tree ─────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_CANDIDATES = [
    os.path.join(os.path.dirname(_HERE), "backend"),   # <repo>/backend
    "/opt/cloud-iot/backend",                          # deployed tree
]
for _c in _CANDIDATES:
    if os.path.isdir(os.path.join(_c, "app")):
        sys.path.insert(0, _c)
        break

_failures: list[str] = []
_checks = 0


def check(label: str, ok: bool, got: object, expected: object) -> None:
    global _checks
    _checks += 1
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {label}")
    print(f"         expected: {expected}")
    print(f"         got     : {got}")
    if not ok:
        _failures.append(label)


# ── The same session doubles the test uses ───────────────────────────────────

@dataclass
class FakeSession:
    type: str = "electricity"
    status: str = "completed"
    started_at: datetime | None = None
    ended_at: datetime | None = None
    energy_kwh: float | None = None
    water_liters: float | None = None


_T0 = datetime(2026, 10, 1, 12, 0, 0)


def elec(minutes: float, kwh: float | None, *, status: str = "completed") -> FakeSession:
    return FakeSession(type="electricity", status=status, started_at=_T0,
                       ended_at=_T0 + timedelta(minutes=minutes), energy_kwh=kwh)


def main() -> int:
    print("=" * 78)
    print("scikit-learn range verification — mirrors")
    print(f"  {MIRRORS}")
    print("=" * 78)
    print()

    print("ENVIRONMENT")
    print(f"  python       : {sys.version.split()[0]}  ({struct.calcsize('P') * 8}-bit)")
    print(f"  executable   : {sys.executable}")

    try:
        import sklearn
    except ImportError as e:
        print(f"  scikit-learn : ABSENT ({e})")
        print()
        print("RESULT: CANNOT VERIFY — scikit-learn is not importable here.")
        print()
        print("  On the DEV BOX this is expected and the pytest version simply skips.")
        print("  On a CABINET this is a FAILURE, not a skip: prediction_service.train()")
        print("  catches the ImportError and logs 'Failed to train', so predictions would")
        print("  silently stop existing with one ERROR line as the only trace.")
        print()
        print("  Do NOT stamp the scikit-learn range as verified on this output.")
        return 2

    print(f"  scikit-learn : {sklearn.__version__}")

    try:
        import numpy
        print(f"  numpy        : {numpy.__version__}")
    except ImportError:
        print("  numpy        : ABSENT — train() cannot build X/y without it")

    # Does the installed version actually satisfy the declared range?
    try:
        from packaging.specifiers import SpecifierSet
        in_range = sklearn.__version__ in SpecifierSet(">=1.5,<2")
    except Exception:
        in_range = None
    print(f"  in >=1.5,<2  : {in_range if in_range is not None else 'could not evaluate'}")
    print()

    from app.services.prediction_service import PredictionService, MIN_SESSIONS

    print(f"MIN_SESSIONS = {MIN_SESSIONS}")
    print()

    # ── 1. Untrained service answers None, never 0.0 ─────────────────────────
    print("CHECK 1 — an untrained model returns None, not zero")
    svc = PredictionService()
    out = svc.predict_electricity(60)
    check("predict_electricity before training is None", out is None, out, None)
    check("electricity_ready is False", svc.electricity_ready is False,
          svc.electricity_ready, False)
    print()

    # ── 2. Below the threshold it must not train ─────────────────────────────
    print(f"CHECK 2 — {MIN_SESSIONS - 1} sessions must NOT train")
    svc = PredictionService()
    few = [elec(30 * i, float(i)) for i in range(1, MIN_SESSIONS)]
    res = svc.train(few)
    check(f"train({MIN_SESSIONS - 1} sessions) -> electricity_trained False",
          res["electricity_trained"] is False, res, {"electricity_trained": False})
    print()

    # ── 3. The real relationship is recovered — the version check ────────────
    print("CHECK 3 — real scikit-learn recovers y = 0.5x from a clean linear set")
    svc = PredictionService()
    sessions = [elec(m, 0.5 * m) for m in (20, 40, 60, 80, 100, 120)]
    print("         input: 6 completed sessions, 0.5 kWh per minute")
    res = svc.train(sessions)
    check("train() -> electricity_trained True",
          res["electricity_trained"] is True, res["electricity_trained"], True)

    if not res["electricity_trained"]:
        print()
        print("  Training failed, so the remaining checks cannot run. train() swallows every")
        print("  exception and logs it, so look for 'Failed to train electricity model' in")
        print("  the backend log for the real reason.")
        return 1

    out = svc.predict_electricity(200)
    pred = out["predicted_consumption"] if out else None
    ok = pred is not None and abs(pred - 100.0) <= 1e-6 * 100.0
    check("predict_electricity(200) == 100.0 kWh", ok, pred, "100.0 (+/- 1e-6 rel)")
    check("unit is kWh", bool(out) and out["unit"] == "kWh",
          out.get("unit") if out else None, "kWh")
    check("type is electricity", bool(out) and out["type"] == "electricity",
          out.get("type") if out else None, "electricity")
    print()

    # ── 4. X really was MINUTES — readable from the fitted model ─────────────
    print("CHECK 4 — the fitted coefficient proves X was minutes, not seconds")
    print("         (a /60 error would still train and still predict, with every")
    print("          coefficient out by a factor of 60 and no error anywhere)")
    model = svc._electricity_model
    coef = float(model.coef_[0])
    intercept = float(model.intercept_)
    ok_coef = abs(coef - 0.5) <= 1e-6
    check("coef_[0] == 0.5 kWh per MINUTE", ok_coef, round(coef, 9), "0.5")
    check("intercept_ ~= 0", abs(intercept) <= 1e-6, round(intercept, 9), "0.0 (+/- 1e-6)")
    if not ok_coef and abs(coef - 0.5 / 60.0) <= 1e-6:
        print("         NOTE: coef matches 0.5/60 — X is in SECONDS. That is the unit bug.")
    print()

    # ── Verdict ──────────────────────────────────────────────────────────────
    print("=" * 78)
    if _failures:
        print(f"RESULT: FAILED — {len(_failures)} of {_checks} checks failed")
        for f in _failures:
            print(f"  - {f}")
        print()
        print("  Do NOT stamp the scikit-learn range as verified.")
        return 1

    print(f"RESULT: PASSED — {_checks}/{_checks} checks, scikit-learn {sklearn.__version__}")
    print()
    print("  This output is the evidence for `scikit-learn>=1.5,<2` in")
    print("  backend/requirements.txt. Paste it back so the comment can be stamped with")
    print("  today's date, this cabinet, and this version.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
