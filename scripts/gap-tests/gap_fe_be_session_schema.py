#!/usr/bin/env python3
"""
GAP: SessionResponse Pydantic schema vs frontend Session TypeScript interface
LAYER: FE<->BE
TOOL: custom Python schema inspector (no extra deps)

Verifies that the Pydantic SessionResponse schema exposes all fields
that the frontend Session TypeScript interface consumes. Any field present
in the TS interface but absent from the Pydantic schema will silently return
None/undefined to the browser — invisible at runtime, broken in production.

Known confirmed gap: `customer_name` is in the TS interface (optional) but
absent from SessionResponse. The controls/customer_sessions routers inject it
only in WS broadcast dicts — never in REST responses. The sessions router
returns raw SQLAlchemy objects which have no customer_name column.

Exit code 0 = all required fields present.
Exit code 1 = fields missing from Pydantic schema.
"""
import sys
import os

# Ensure backend package is importable
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO_ROOT)

# Fields the frontend Session TypeScript interface declares it uses
# (from frontend/src/store/index.ts interface Session)
FRONTEND_SESSION_FIELDS = {
    "id",
    "pedestal_id",
    "socket_id",
    "type",
    "status",
    "started_at",
    "ended_at",
    "energy_kwh",
    "water_liters",
    "customer_id",
    "deny_reason",
    # customer_name is declared optional in TS but injected in Playwright mocks
    # and used in Quick Status / AllSessionsOverview — must be in REST response
    "customer_name",
}

def main():
    try:
        from backend.app.schemas.session import SessionResponse
    except ImportError as e:
        print(f"IMPORT ERROR: {e}")
        print("Run from repo root with the backend venv active.")
        sys.exit(1)

    pydantic_fields = set(SessionResponse.model_fields.keys())

    missing = FRONTEND_SESSION_FIELDS - pydantic_fields
    extra   = pydantic_fields - FRONTEND_SESSION_FIELDS

    print("GAP: FE<->BE | session schema consistency check")
    print(f"  Pydantic fields:  {sorted(pydantic_fields)}")
    print(f"  Frontend expects: {sorted(FRONTEND_SESSION_FIELDS)}")
    print()

    if missing:
        print(f"FAIL: {len(missing)} field(s) in frontend interface but NOT in Pydantic schema:")
        for f in sorted(missing):
            print(f"  MISSING: {f}")
        print()
        print("FIX: Add the missing fields to backend/app/schemas/session.py")
        print("     OR remove them from the frontend interface if they are WS-only.")
        sys.exit(1)
    else:
        print(f"PASS: All {len(FRONTEND_SESSION_FIELDS)} frontend-consumed fields present in Pydantic schema.")
        if extra:
            print(f"INFO: {len(extra)} extra field(s) in schema not in TS interface (not a problem):")
            for f in sorted(extra):
                print(f"  EXTRA: {f}")
        sys.exit(0)


if __name__ == "__main__":
    main()
