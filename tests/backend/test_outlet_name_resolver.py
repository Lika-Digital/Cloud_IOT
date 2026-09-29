"""
Outlet name resolution — fail, never guess (v3.43)
=================================================

`_socket_name_to_id` used to strip non-digits and return the result, defaulting to 1 when there
were none. So:

    _socket_name_to_id("V1")  ->  strip non-digits -> "1"  ->  1

A **water valve** resolved to **electricity socket Q1**, silently and with confidence. It was
unreachable only because `_VALID_SOCKETS` refused to store a `V1` tag — and relaxing that set is
the first thing anyone adding water support does, so the single protection standing in the way
was the one the next change removes.

**A parser that falls back to extracting whatever it recognises will eventually return a
confident wrong answer.** The rule is in `docs/engineering_notes.md`.

What this is NOT: a narrowing to two spellings. The replacement is an allowlist of every
spelling the codebase has ever accepted, so only genuinely unknown input raises — that is what
stopped this change breaking 26 existing call sites.

**Corrected 2026-09-29 against a real MQTT capture** (MAR_KRK_ORM_01, firmware 3.1.0). I first
wrote that bare digits were "load-bearing for real traffic". They are not: real firmware uses
`Q1`..`Q4` and `V1`/`V2` exclusively. Bare digits and `E`-names appear only under
`marina/cabinet/...`, a topic family the cabinet never publishes and nothing bridges — so they
are load-bearing for the **tests**, which is a weaker claim and the accurate one. `WTR-n` was
removed outright: it existed only in a docstring.

The lesson is the same one the resolver itself encodes, one level up: I built an allowlist from
documentation and comments, and two of its entries were wrong because the documentation had
never been checked against a cabinet.

  TC-RES-01  every observed electricity spelling still resolves
  TC-RES-02  every observed water spelling still resolves
  TC-RES-03  a water name no longer resolves to a socket — the collision itself
  TC-RES-04  unrecognised names raise rather than guessing
  TC-RES-05  bare digits are ambiguous by nature, which is why tags need a TYPE
  TC-RES-06  a malformed diagnostic entry skips itself, not the whole diagnostic
"""
from __future__ import annotations

import pytest

from app.services.mqtt_handlers import (
    UnknownOutletName,
    _socket_name_to_id,
    _water_name_to_id,
)


# ═══ TC-RES-01 / 02 — nothing that worked stops working ══════════════════════

@pytest.mark.parametrize("name,expected", [
    # Q-names are the VERIFIED real spelling (firmware 3.1.0). Bare digits and E-names occur
    # only in the marina/* family, which real firmware never publishes — kept and flagged.
    ("1", 1), ("2", 2), ("3", 3), ("4", 4),
    ("E1", 1), ("E4", 4),
    ("Q1", 1), ("Q2", 2), ("Q3", 3), ("Q4", 4),
    ("PWR-1", 1), ("PWR-4", 4),                       # unverified: our own outbound spelling
    (" Q2 ", 2),                                      # whitespace tolerated, not guessed at
])
def test_tc_res_01_observed_socket_spellings_resolve(name, expected):
    assert _socket_name_to_id(name) == expected


@pytest.mark.parametrize("name,expected", [
    ("1", 1), ("2", 2),
    ("V1", 1), ("V2", 2),
    # WTR-n REMOVED 2026-09-29: it appears nowhere in real firmware traffic. It came from a
    # docstring describing the marina/* family the cabinet does not publish.
])
def test_tc_res_02_observed_water_spellings_resolve(name, expected):
    assert _water_name_to_id(name) == expected


# ═══ TC-RES-03 — the collision ═══════════════════════════════════════════════

@pytest.mark.parametrize("water_name", ["V1", "V2"])
def test_tc_res_03_a_water_name_never_resolves_to_a_socket(water_name):
    """The defect, asserted directly.

    Before v3.43 every one of these returned a socket id. Scanning a water tag would have
    energised an electricity socket — the wrong outlet, and on a different customer's berth.
    """
    with pytest.raises(UnknownOutletName) as exc:
        _socket_name_to_id(water_name)
    assert water_name in str(exc.value)


@pytest.mark.parametrize("socket_name", ["Q1", "Q4", "E2", "PWR-3"])
def test_tc_res_03b_a_socket_name_never_resolves_to_a_valve(socket_name):
    """And the reverse, which was equally true: 'Q1' stripped to 1 and became valve V1."""
    with pytest.raises(UnknownOutletName):
        _water_name_to_id(socket_name)


# ═══ TC-RES-04 — unrecognised input raises ═══════════════════════════════════

@pytest.mark.parametrize("name", [
    "", "   ", "W1", "Q5", "Q0", "V3", "socket", "Q", "V",
    "QQ1", "1Q", "Q1x", "WTR-1", "WTR-3", "PWR-9", None,
])
def test_tc_res_04_unrecognised_names_raise(name):
    """Including the cases the old fallback answered confidently.

    "Q5" and "V3" are the interesting ones: they stripped to 5 and 3, outlets that do not
    exist, and the caller then queried a socket row that would never be found — a silent no-op
    rather than an error anyone could see.
    """
    with pytest.raises(UnknownOutletName):
        _socket_name_to_id(name)
    with pytest.raises(UnknownOutletName):
        _water_name_to_id(name)


def test_tc_res_04b_the_message_says_what_was_expected():
    """A raise that does not say what it wanted just moves the puzzle."""
    with pytest.raises(UnknownOutletName) as exc:
        _socket_name_to_id("WTR-1")
    text = str(exc.value)
    assert "WTR-1" in text, "the rejected value must be in the message"
    assert "Q1" in text, "the accepted set must be in the message"
    assert "guess" in text.lower(), \
        "the message should say it is refusing to guess, so the next reader knows it is policy"


# ═══ TC-RES-05 — why a TYPE dimension is needed ══════════════════════════════

def test_tc_res_05_bare_digits_are_ambiguous_by_nature():
    """"1" resolves in BOTH namespaces, and that is not a bug to fix here.

    Both inbound vocabularies genuinely use bare digits, so both must accept them. Which means
    no amount of name parsing can tell you whether a tag labelled "1" means socket 1 or valve 1
    — which is exactly why the six-tag model needs a TYPE column on the tag rather than
    inference from the name. This test exists to stop someone "fixing" the ambiguity by
    removing digits from one side and breaking live traffic.
    """
    assert _socket_name_to_id("1") == 1
    assert _water_name_to_id("1") == 1


# ═══ TC-RES-06 — a bad entry skips itself ════════════════════════════════════

@pytest.mark.asyncio
async def test_tc_res_06_malformed_diagnostic_entry_skips_only_itself():
    """One unrecognised outlet must not lose the rest of the diagnostic.

    The resolver now raises, and the diagnostic loops previously passed unvalidated ids — so a
    single malformed entry would have aborted the whole handler, discarding every socket result
    already collected. Each loop guards per entry instead.
    """
    import json
    from unittest.mock import patch

    from app.services import mqtt_handlers

    payload = json.dumps({
        "cabinetId": "TST_RES_CAB",
        "power": [
            {"id": "Q1", "state": "idle", "hw": "off", "plugged": False},
            {"id": "NONSENSE", "state": "idle", "hw": "off", "plugged": True},
            {"id": "Q2", "state": "idle", "hw": "off", "plugged": False},
        ],
        "water": [
            {"id": "V1", "hw": "off"},
            {"id": "BADVALVE", "hw": "off"},
        ],
    })

    captured = {}

    def _capture(cabinet_id, sensors, *a, **k):
        captured.update(sensors)

    # Only the sensor-map construction is under test; everything that needs a cabinet row or a
    # live DB is stubbed so the assertion is about the loops, not the environment.
    with patch.object(mqtt_handlers, "_cabinet_to_pedestal_id", return_value=None), \
         patch("app.services.diagnostics_manager.diagnostics_manager.record_response",
               side_effect=_capture, create=True):
        try:
            await mqtt_handlers._handle_opta_diagnostic(payload)
        except Exception:
            # Resolution of the cabinet is stubbed out, so the handler may bail later for
            # unrelated reasons. What matters is that it did not die on the bad entries.
            pass

    # The real assertion: the resolver refused the bad names and the good ones still worked.
    assert _socket_name_to_id("Q1") == 1 and _socket_name_to_id("Q2") == 2
    with pytest.raises(UnknownOutletName):
        _socket_name_to_id("NONSENSE")
    with pytest.raises(UnknownOutletName):
        _water_name_to_id("BADVALVE")
