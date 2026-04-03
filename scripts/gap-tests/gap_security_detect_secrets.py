#!/usr/bin/env python3
"""
GAP: Hardcoded credential scan
LAYER: security
TOOL: detect-secrets

Reads the detect-secrets JSON output from stdin and exits non-zero if any
potential secrets are found. Designed to be piped from `detect-secrets scan`.

Usage:
    detect-secrets scan backend/app/ frontend/src/ 2>/dev/null | python gap_security_detect_secrets.py

Exit code 0 = no secrets found.
Exit code 1 = potential secrets detected (review before committing).
"""
import sys
import json

def main():
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        print(f"PARSE_ERROR: could not parse detect-secrets JSON output: {e}")
        sys.exit(1)

    results = data.get("results", {})
    found = sum(len(v) for v in results.values())

    if found > 0:
        print(f"FAIL: detect-secrets found {found} potential secret(s):")
        for path, secrets in results.items():
            for s in secrets:
                print(f"  {path}:{s.get('line_number','?')} [{s.get('type','?')}]")
        sys.exit(1)
    else:
        print(f"PASS: no secrets detected across {len(results)} files scanned")
        sys.exit(0)


if __name__ == "__main__":
    main()
