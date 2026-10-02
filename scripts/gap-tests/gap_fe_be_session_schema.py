#!/usr/bin/env python3
"""
GAP: SessionResponse Pydantic schema vs frontend Session TypeScript interface
LAYER: FE<->BE
TOOL: custom inspector — PARSES THE TYPESCRIPT, no extra deps

Verifies that the Pydantic SessionResponse schema exposes every field the frontend Session
interface consumes. A field in the TS interface but absent from the schema returns undefined
to the browser — invisible at runtime, broken in production.

REWRITTEN 2026-10-02. WHY THE OLD VERSION COULD NOT WORK
--------------------------------------------------------
This script used to carry a hand-typed literal:

    FRONTEND_SESSION_FIELDS = {"id", "pedestal_id", ...}   # someone read the TS once

That is a CLAIM ABOUT the frontend, not a CHECK OF it. Adding a field to the TypeScript
interface did not make this fail, because nothing compared the two — so the one test whose
entire purpose was catching FE/BE drift was blind to the most likely way drift happens.

It is the same shape as the three docstring-contradicts-code findings in this codebase (NFC
provisioning, /api/analytics, usage/history): a statement about the system, placed where a
reader will trust it, that nothing verifies. See docs/engineering_notes.md.

It now reads `frontend/src/store/index.ts` and parses the interface. If the file moves or the
interface is renamed, this fails loudly rather than falling back to a stale literal — a
silent fallback would reintroduce exactly the problem.

Exit 0 = every frontend-consumed field is present.
Exit 1 = fields missing, or the TypeScript could not be read.
"""
import io
import os
import re
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO_ROOT)

TS_FILE = os.path.join(REPO_ROOT, "frontend", "src", "store", "index.ts")
TS_INTERFACE = "Session"

# `  socket_id: number | null`  /  `  customer_name?: string | null`
_FIELD_RE = re.compile(r"^\s*(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?P<opt>\?)?\s*:", re.MULTILINE)


def parse_ts_interface(path: str, name: str) -> tuple[set[str], set[str]]:
    """(all fields, optional fields) declared by `export interface <name> { ... }`.

    Brace-counted rather than regex-matched to the closing brace, so a nested object type
    inside the interface does not truncate the parse.
    """
    if not os.path.exists(path):
        raise RuntimeError(
            f"{path} does not exist. This check reads the real TypeScript; it must not fall "
            f"back to a hand-copied field list, because that is the bug it was rewritten to fix."
        )
    src = io.open(path, encoding="utf-8").read()

    m = re.search(r"\bexport\s+interface\s+" + re.escape(name) + r"\s*\{", src)
    if not m:
        raise RuntimeError(
            f"`export interface {name}` not found in {os.path.relpath(path, REPO_ROOT)}. "
            f"It was renamed or moved — update TS_FILE/TS_INTERFACE here rather than letting "
            f"this check quietly verify nothing."
        )

    i = m.end()           # just past the opening brace
    depth = 1
    while i < len(src) and depth:
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
        i += 1
    body = src[m.end():i - 1]

    fields, optional = set(), set()
    for f in _FIELD_RE.finditer(body):
        fields.add(f.group("name"))
        if f.group("opt"):
            optional.add(f.group("name"))
    return fields, optional


def main():
    print("GAP: FE<->BE | session schema consistency check")
    try:
        ts_fields, ts_optional = parse_ts_interface(TS_FILE, TS_INTERFACE)
    except RuntimeError as e:
        print(f"FAIL: {e}")
        sys.exit(1)

    if not ts_fields:
        print("FAIL: the interface parsed to zero fields — the parser is broken, and this "
              "check would pass without comparing anything.")
        sys.exit(1)

    try:
        from backend.app.schemas.session import SessionResponse
    except ImportError as e:
        print(f"FAIL: cannot import SessionResponse: {e}")
        print("      Run from the repo root with the backend venv active.")
        sys.exit(1)

    pydantic_fields = set(SessionResponse.model_fields.keys())

    # An OPTIONAL TS field (`name?:`) is still required in the response when the UI renders
    # it: `customer_name?` was declared optional and the UI showed it, which is how its
    # absence from the REST payload went unnoticed. Optionality in TypeScript describes the
    # type, never whether a screen depends on it.
    missing = ts_fields - pydantic_fields
    extra = pydantic_fields - ts_fields

    print(f"  Parsed from:      {os.path.relpath(TS_FILE, REPO_ROOT)} (interface {TS_INTERFACE})")
    print(f"  Frontend expects: {sorted(ts_fields)}")
    print(f"  Optional in TS:   {sorted(ts_optional) or '[]'}")
    print(f"  Pydantic fields:  {sorted(pydantic_fields)}")
    print()

    if missing:
        print(f"FAIL: {len(missing)} field(s) in the frontend interface but NOT in the schema:")
        for f in sorted(missing):
            tag = " (optional in TS, but still rendered if the UI reads it)" if f in ts_optional else ""
            print(f"  MISSING: {f}{tag}")
        print()
        print("FIX: add them to backend/app/schemas/session.py, or remove them from the")
        print("     TypeScript interface if they are websocket-only.")
        sys.exit(1)

    print(f"PASS: all {len(ts_fields)} frontend-consumed fields are present in the schema.")
    if extra:
        print(f"INFO: {len(extra)} schema field(s) the TS interface does not declare "
              f"(not a problem — the backend may legitimately send more):")
        for f in sorted(extra):
            print(f"  EXTRA: {f}")
    sys.exit(0)


if __name__ == "__main__":
    main()
