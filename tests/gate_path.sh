#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  Which commit gate runs — decided HERE, mechanically, never by whoever commits.
#  Owner, 2026-10-16. Called by .githooks/pre-commit; tested by tests/backend/test_gate_path.py.
#
#  The rule: if the staged change (`git diff --cached --name-only --no-renames`) is ONLY files
#  ending in `.md`, the docs-only check runs; ANY other file — or nothing staged at all — runs the
#  full commit gate. No exceptions and no flag to bypass it.
#
#    --no-renames  a rename a.py -> a.md must list BOTH names, or the .py would vanish from the
#                  list and a code change would pass as documentation.
#    nothing staged -> full: "only .md" must not be true of an empty list.
#
#  Documentation is not automatically harmless: some tests READ .md files (TC-UIR-01c reads
#  the "Block 4" row of docs/ui_v2_spec.md §0.2). The docs-only check therefore runs every test
#  file whose source names a .md file in a string literal (`.md"` or `.md'`) — found by the same
#  mechanical rule each time, so a new test that reads a document joins without anyone listing it.
#
#  Output, on stdout, one line each:
#    GATE_PATH=docs|full
#    GATE_REASON=<plain sentence>
#    GATE_DOC_TESTS=<space-separated test files>     (docs path only)
# ─────────────────────────────────────────────────────────────────────────────
set -uo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT" || exit 2

CHANGED="$(git diff --cached --name-only --no-renames)"

if [ -z "$CHANGED" ]; then
    echo "GATE_PATH=full"
    echo "GATE_REASON=full gate: no staged file list to judge, so not documentation-only"
    exit 0
fi

NON_MD="$(printf '%s\n' "$CHANGED" | grep -v '\.md$' || true)"
if [ -n "$NON_MD" ]; then
    COUNT=$(printf '%s\n' "$NON_MD" | wc -l | tr -d ' ')
    FIRST=$(printf '%s\n' "$NON_MD" | head -5 | tr '\n' ' ')
    echo "GATE_PATH=full"
    echo "GATE_REASON=full gate: ${COUNT} changed file(s) that are not .md: ${FIRST% }"
    exit 0
fi

MD_COUNT=$(printf '%s\n' "$CHANGED" | wc -l | tr -d ' ')
DOC_TESTS="$(grep -lE "\.md[\"']" tests/backend/test_*.py 2>/dev/null | sort | tr '\n' ' ')"
echo "GATE_PATH=docs"
echo "GATE_REASON=docs-only: all ${MD_COUNT} changed file(s) are .md"
echo "GATE_DOC_TESTS=${DOC_TESTS% }"
exit 0
