#!/usr/bin/env python3
import argparse
import csv
import json
import os
import re
import subprocess
import sys
from typing import List, Optional, Tuple

SF_ALIAS = "fortinet"
DEFAULT_STATES = ["IA", "NE", "SD"]
DEFAULT_OUTPUT = "campaigns/sfdc-accounts.csv"


def _run_sf(args: List[str]) -> Tuple[bool, str]:
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return False, "sf CLI timed out after 30s"
    except Exception as exc:
        return False, f"sf CLI error: {exc}"

    if proc.returncode != 0:
        return False, proc.stderr.strip() or proc.stdout.strip()
    return True, proc.stdout


def _normalize_state(state: Optional[str]) -> str:
    return (state or "").strip().upper()


def _normalize_phone(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    digits = re.sub(r"\D+", "", raw)
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    return None


def _state_variants(states: List[str]) -> List[str]:
    variants = []
    for s in states:
        s = s.strip()
        if not s:
            continue
        variants.extend([s.upper(), s.lower(), s.title()])
    # preserve order, de-dupe
    seen = set()
    ordered = []
    for v in variants:
        if v not in seen:
            seen.add(v)
            ordered.append(v)
    return ordered


def _build_soql(states: List[str]) -> str:
    state_list = ",".join([f"'{s}'" for s in _state_variants(states)])
    return (
        "SELECT Id, Name, Phone, BillingState, Type, Industry "
        "FROM Account "
        "WHERE Phone != null "
        f"AND BillingState IN ({state_list}) "
        "AND IsDeleted = false "
        "ORDER BY Name"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Pull Salesforce accounts into campaign CSV.")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Output CSV path")
    parser.add_argument("--states", default=",".join(DEFAULT_STATES), help="Comma-separated states")
    args = parser.parse_args()

    states = [s.strip() for s in args.states.split(",") if s.strip()]
    if not states:
        print("No states provided; aborting.")
        return 1

    soql = _build_soql(states)
    cmd = [
        "sf",
        "data",
        "query",
        "--query",
        soql,
        "--json",
        "--target-org",
        SF_ALIAS,
    ]

    ok, out = _run_sf(cmd)
    if not ok:
        print(f"Salesforce query failed: {out}")
        return 1

    try:
        payload = json.loads(out)
        records = payload.get("result", {}).get("records", [])
    except Exception as exc:
        print(f"Failed to parse Salesforce output: {exc}")
        return 1

    total = len(records)
    valid = 0
    skipped = 0

    rows = []
    for rec in records:
        phone = _normalize_phone(rec.get("Phone"))
        if not phone:
            skipped += 1
            continue
        name = rec.get("Name") or ""
        state = _normalize_state(rec.get("BillingState"))
        industry = rec.get("Industry") or rec.get("Type") or ""
        notes = f"{name} | {state} | {industry}".strip()

        rows.append(
            {
                "phone": phone,
                "name": name,
                "account": name,
                "state": state,
                "type": rec.get("Type") or "",
                "sf_account_id": rec.get("Id") or "",
                "notes": notes,
            }
        )
        valid += 1

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "phone",
                "name",
                "account",
                "state",
                "type",
                "sf_account_id",
                "notes",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"Total queried: {total}")
    print(f"Valid: {valid}")
    print(f"Skipped: {skipped}")
    print(f"Output: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
