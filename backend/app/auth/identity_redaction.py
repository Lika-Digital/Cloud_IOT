"""Customer identity is for admin only — part B of block 1, 2026-10-12.

OWNER'S DECISION, binding (rule 13, docs/engineering_notes.md): marina staff must not see
customer data. The customer's identity lives in the ERP; the cabinet shows the session and the
consumption, not who the customer is. Only admin sees more.

This is the ONE list. Every channel that hands session data to a non-admin operator — the /ws
broadcast, GET /api/sessions, usage history, reconciliation divergence — strips these keys at
any depth, so a field added to a payload later is covered by name, not by remembering. A new
identity field belongs HERE, and tests/backend/test_identity_redaction.py checks the list.

Removed, not nulled: a present-but-null key cannot be told apart from "this session had no
customer", and a client that renders the key would still render a column for it.
"""
from __future__ import annotations

from typing import Any

IDENTITY_KEYS: frozenset[str] = frozenset({"customer_id", "customer_name", "nfc_user_id", "erp_ref"})


def sees_identity(role: str | None) -> bool:
    """Fail safe: an unknown or missing role gets the redacted view."""
    return role == "admin"


def redact(obj: Any) -> Any:
    """A copy of `obj` with every IDENTITY_KEYS entry removed from every dict, at any depth."""
    if isinstance(obj, dict):
        return {k: redact(v) for k, v in obj.items() if k not in IDENTITY_KEYS}
    if isinstance(obj, (list, tuple)):
        return [redact(x) for x in obj]
    return obj
