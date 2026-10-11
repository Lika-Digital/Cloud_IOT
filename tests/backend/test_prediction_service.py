"""prediction_service — the scikit-learn call path.

WHY THIS FILE EXISTS (2026-10-10)
---------------------------------
Until now this path had NO TEST AT ALL. That is a finding, not a footnote.

`scikit-learn` is not installed in the development venv — it publishes no 32-bit Windows
wheel and the dev interpreter is Python 3.13 32-bit — and the full backend suite passed
without it, 1000+ tests green, because nothing ever imported it. So when the question came
up of relaxing `scikit-learn==1.5.2` to a range, the prescribed verification ("run the suite
against the installed version") would have produced a green number that proved nothing
whatsoever about scikit-learn.

Hence two kinds of test here, with a deliberate split:

  STUB TESTS      run everywhere, including the gate. They replace sklearn with a double
                  and verify OUR side of the contract: that the lazy import is reached, that
                  X is minutes (not seconds) in an (n, 1) matrix, that y is the right
                  measurement, that the MIN_SESSIONS boundary holds, and that an untrained
                  model returns None rather than zero.

  REAL-SKLEARN    skips when sklearn is absent, which on the dev box is always. It is an
                  explicit acceptance step run on the cabinet, where sklearn 1.9.0 and
                  Python 3.14 actually live. It is the only thing that can verify the range
                  resolves and the version's API still behaves.

The split follows the rule this project arrived at the hard way: a local green proves our
code works with a version; only the target machine can prove the version installs there.
Neither result may be read as the other.

A FINDING RECORDED BY test_missing_sklearn_... BELOW
---------------------------------------------------
`train()` wraps everything in `except Exception` and calls `logger.error`. A missing
scikit-learn is therefore indistinguishable from a genuine training failure: predictions
silently stop existing and the only trace is one ERROR line. That behaviour is pinned here
as it stands, NOT fixed — changing it is a separate decision.
"""
from __future__ import annotations

import sys
import types
from dataclasses import dataclass
from datetime import datetime, timedelta

import pytest


# ── Session doubles ───────────────────────────────────────────────────────────

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
    return FakeSession(
        type="electricity", status=status,
        started_at=_T0, ended_at=_T0 + timedelta(minutes=minutes), energy_kwh=kwh,
    )


def water(minutes: float, liters: float | None, *, status: str = "completed") -> FakeSession:
    return FakeSession(
        type="water", status=status,
        started_at=_T0, ended_at=_T0 + timedelta(minutes=minutes), water_liters=liters,
    )


# ── The sklearn double ────────────────────────────────────────────────────────

class FakeLinearRegression:
    """Records what it was handed, returns a value we chose."""

    instances: list["FakeLinearRegression"] = []
    next_prediction: float = 42.0

    def __init__(self):
        self.X = None
        self.y = None
        self.fit_calls = 0
        FakeLinearRegression.instances.append(self)

    def fit(self, X, y):
        self.X, self.y = X, y
        self.fit_calls += 1
        return self

    def predict(self, X):
        self.predict_X = X
        return [FakeLinearRegression.next_prediction] * len(X)


@pytest.fixture
def fake_sklearn(monkeypatch):
    """Put a double where `from sklearn.linear_model import LinearRegression` will find it.

    Patched into sys.modules rather than into prediction_service, because the import is
    INSIDE the method — the point is to prove that lazy import is actually reached. If the
    import were moved to module level this fixture would stop having any effect and the
    tests would fail, which is the correct outcome: the laziness is load-bearing on a
    machine with no sklearn.
    """
    sklearn_mod = types.ModuleType("sklearn")
    linear_mod = types.ModuleType("sklearn.linear_model")
    linear_mod.LinearRegression = FakeLinearRegression
    sklearn_mod.linear_model = linear_mod
    monkeypatch.setitem(sys.modules, "sklearn", sklearn_mod)
    monkeypatch.setitem(sys.modules, "sklearn.linear_model", linear_mod)
    FakeLinearRegression.instances.clear()
    FakeLinearRegression.next_prediction = 42.0
    yield FakeLinearRegression
    FakeLinearRegression.instances.clear()


@pytest.fixture
def svc():
    """A fresh service — the module-level singleton carries trained state between tests."""
    from app.services.prediction_service import PredictionService
    return PredictionService()


# ── The module must import with no sklearn present ────────────────────────────

def test_module_imports_without_sklearn_installed():
    """The dev box has no sklearn and must still be able to import this module.

    If someone moves `from sklearn.linear_model import ...` to module scope, the whole
    backend stops importing on any machine without scikit-learn — and since the import sits
    behind `except Exception` in train(), the damage would show up as "no predictions"
    rather than as an import error.
    """
    import importlib
    mod = importlib.import_module("app.services.prediction_service")
    assert mod.prediction_service is not None
    src_has_module_level_import = any(
        line.startswith("from sklearn") or line.startswith("import sklearn")
        for line in open(mod.__file__, encoding="utf-8").read().splitlines()
    )
    assert not src_has_module_level_import, (
        "sklearn is imported at module level; on a machine without scikit-learn this breaks "
        "the entire backend import, not just predictions"
    )


# ── What gets handed to the model ─────────────────────────────────────────────

def test_x_is_duration_in_minutes_and_y_is_energy(svc, fake_sklearn):
    """X must be minutes in an (n, 1) matrix, y the kWh figures, in the same order.

    Seconds instead of minutes would still train and still predict — with every coefficient
    out by 60 and no error anywhere. The units are the thing worth pinning.
    """
    sessions = [elec(30, 1.0), elec(60, 2.0), elec(90, 3.0), elec(120, 4.0), elec(150, 5.0)]
    result = svc.train(sessions)

    assert result["electricity_trained"] is True
    assert len(fake_sklearn.instances) == 1
    model = fake_sklearn.instances[0]
    assert model.fit_calls == 1

    assert model.X.shape == (5, 1), f"expected an (n, 1) matrix, got {model.X.shape}"
    assert [row[0] for row in model.X.tolist()] == [30.0, 60.0, 90.0, 120.0, 150.0], (
        "durations are not in minutes — check the /60 in train()"
    )
    assert model.y.tolist() == [1.0, 2.0, 3.0, 4.0, 5.0]


def test_water_trains_on_liters_not_kwh(svc, fake_sklearn):
    sessions = [water(10, 100.0), water(20, 200.0), water(30, 300.0),
                water(40, 400.0), water(50, 500.0)]
    result = svc.train(sessions)
    assert result["water_trained"] is True
    assert result["electricity_trained"] is False
    assert fake_sklearn.instances[0].y.tolist() == [100.0, 200.0, 300.0, 400.0, 500.0]


# ── MIN_SESSIONS ──────────────────────────────────────────────────────────────

def test_four_sessions_do_not_train_five_do(svc, fake_sklearn):
    from app.services.prediction_service import MIN_SESSIONS
    assert MIN_SESSIONS == 5, "this test encodes the boundary; update it deliberately"

    four = [elec(30 * i, float(i)) for i in range(1, 5)]
    assert svc.train(four)["electricity_trained"] is False
    assert fake_sklearn.instances == [], "fit() was called below MIN_SESSIONS"

    five = four + [elec(150, 5.0)]
    assert svc.train(five)["electricity_trained"] is True


# ── Filtering ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("bad,why", [
    (elec(60, 2.0, status="active"),    "an active session has not finished measuring"),
    (elec(60, None),                    "energy_kwh is None — absence of a measurement"),
    (FakeSession(type="electricity", status="completed",
                 started_at=_T0, ended_at=None, energy_kwh=2.0), "no ended_at"),
    (FakeSession(type="electricity", status="completed",
                 started_at=None, ended_at=_T0, energy_kwh=2.0), "no started_at"),
])
def test_unusable_sessions_are_excluded(svc, fake_sklearn, bad, why):
    """Four good rows plus one unusable row must stay BELOW the threshold.

    energy_kwh is None matters most: on this cabinet 172 of 175 sessions carry no
    consumption_source and the register path has never produced a figure. A None treated as
    a zero would train the model on fabricated points.
    """
    sessions = [elec(30 * i, float(i)) for i in range(1, 5)] + [bad]
    assert svc.train(sessions)["electricity_trained"] is False, (
        f"an unusable session was counted towards MIN_SESSIONS ({why})"
    )


# ── Predicting ────────────────────────────────────────────────────────────────

def test_predict_returns_none_before_training(svc):
    """None, never 0.0. No model is the absence of an answer, not an answer of zero."""
    assert svc.predict_electricity(60) is None
    assert svc.predict_water(60) is None
    assert svc.electricity_ready is False
    assert svc.water_ready is False


def test_predict_payload_and_input_shape(svc, fake_sklearn):
    fake_sklearn.next_prediction = 7.5
    svc.train([elec(30 * i, float(i)) for i in range(1, 6)])

    out = svc.predict_electricity(100)
    assert out == {
        "predicted_duration_minutes": 100,
        "predicted_consumption": 7.5,
        "unit": "kWh",
        "type": "electricity",
    }
    model = fake_sklearn.instances[0]
    assert model.predict_X.shape == (1, 1)
    assert model.predict_X.tolist() == [[100]]


def test_negative_prediction_is_clamped_to_zero(svc, fake_sklearn):
    """Documents current behaviour: a negative prediction becomes 0.0.

    This IS a correction rather than a refusal, and this project treats those with
    suspicion. It is tolerable here only because a prediction is advisory and never billed —
    unlike meter power, where the equivalent clamp hid a 100x fault for a year. Recorded so
    the distinction is deliberate rather than accidental.
    """
    fake_sklearn.next_prediction = -5.0
    svc.train([elec(30 * i, float(i)) for i in range(1, 6)])
    assert svc.predict_electricity(60)["predicted_consumption"] == 0.0


# ── The silent-degradation finding ────────────────────────────────────────────

def test_missing_sklearn_is_swallowed_and_looks_like_a_training_failure(svc, monkeypatch, caplog):
    """PINS CURRENT BEHAVIOUR, DOES NOT ENDORSE IT.

    `train()` catches every exception and logs it. So an absent scikit-learn produces exactly
    the same observable result as a genuine training failure: `electricity_trained: False`
    and one ERROR line. Nothing distinguishes "the library is not installed" from "the data
    would not fit".

    That is how this path stayed unnoticed and untested. Fixing it — separating ImportError
    from a fit failure, or surfacing it in /api/predictions — is a decision, not part of a
    dependency-pin change.
    """
    import logging
    monkeypatch.setitem(sys.modules, "sklearn", None)
    monkeypatch.setitem(sys.modules, "sklearn.linear_model", None)

    sessions = [elec(30 * i, float(i)) for i in range(1, 6)]
    with caplog.at_level(logging.ERROR):
        result = svc.train(sessions)

    assert result == {"electricity_trained": False, "water_trained": False}, (
        "train() must not raise when sklearn is absent — the backend has to keep serving"
    )
    assert svc.predict_electricity(60) is None
    assert any("Failed to train" in r.message or "Failed to train" in r.getMessage()
               for r in caplog.records), (
        "the failure was not even logged, which would make it completely invisible"
    )


# ── Real scikit-learn: the pin verification, run on the cabinet ───────────────

def test_real_sklearn_recovers_a_known_linear_relationship():
    """ACCEPTANCE STEP — skips on the dev box, runs on the cabinet.

    This is the only test here that says anything about the scikit-learn VERSION. It feeds a
    perfectly linear set (0.5 kWh per minute) and requires the model to recover it, which
    exercises the real LinearRegression API and its numerics.

    Expected to SKIP wherever scikit-learn is absent — including every gate run on the
    development machine, which has no 32-bit wheel available. A skip here is not a pass:
    the range on `scikit-learn` in requirements.txt is justified by THIS test running on a
    machine that has the library, and nowhere else.
    """
    sklearn = pytest.importorskip(
        "sklearn",
        reason="scikit-learn absent (no 32-bit Windows wheel on the dev box) — this "
               "verification belongs to the cabinet acceptance run",
    )
    from app.services.prediction_service import PredictionService

    svc = PredictionService()
    sessions = [elec(m, 0.5 * m) for m in (20, 40, 60, 80, 100, 120)]
    result = svc.train(sessions)
    assert result["electricity_trained"] is True, (
        f"real scikit-learn {sklearn.__version__} failed to train on a clean linear set"
    )

    out = svc.predict_electricity(200)
    assert out is not None
    assert out["predicted_consumption"] == pytest.approx(100.0, rel=1e-6), (
        f"scikit-learn {sklearn.__version__} did not recover y = 0.5x; "
        f"got {out['predicted_consumption']}"
    )
    assert out["unit"] == "kWh"
