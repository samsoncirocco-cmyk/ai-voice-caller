#!/usr/bin/env python3
"""
sfdc_live_sync.py — Salesforce REST API live-sync module.

Connects directly to the SFDC REST API using an access token obtained from the
authenticated `sf` CLI. Pulls Accounts and Opportunities modified in the last N
hours (default 24), writes them to the local SQLite accounts.db, and updates
the AI caller state machine for Closed Won / Closed Lost opportunities.

Usage:
  python3 execution/sfdc_live_sync.py                    # pull last 24h
  python3 execution/sfdc_live_sync.py --hours 48         # extend window
  python3 execution/sfdc_live_sync.py --states IA,NE,SD  # filter by state
  python3 execution/sfdc_live_sync.py --dry-run          # preview, no writes

Exit codes: 0 = success, 1 = auth failure, 2 = query failure
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))

from account_db import AccountDB  # noqa: E402

# ── constants ─────────────────────────────────────────────────────────────────

SF_ALIAS       = "fortinet"
SLACK_TOKEN    = os.environ.get("SLACK_BOT_TOKEN", "")
SLACK_CHANNEL  = "C0AJWRGBW3B"   # #ai-caller
DEFAULT_STATES = ["IA", "NE", "SD"]
DEFAULT_HOURS  = 24
API_VERSION    = "v59.0"

# Stage → caller state transition table
STAGE_TO_CALLER_STATE: Dict[str, str] = {
    "Closed Won":  "converted",
    "Closed Lost": "not_interested",
}


# ── Slack helper ──────────────────────────────────────────────────────────────

def _post_slack(text: str) -> bool:
    if not SLACK_TOKEN:
        return False
    try:
        import requests as _req
        r = _req.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {SLACK_TOKEN}"},
            json={"channel": SLACK_CHANNEL, "text": text},
            timeout=20,
        )
        return r.json().get("ok", False)
    except Exception:
        return False


# ── sf CLI helpers ────────────────────────────────────────────────────────────

def _run_sf(args: List[str], timeout: int = 60) -> Tuple[bool, str]:
    """Run a `sf` CLI command; return (success, stdout/stderr)."""
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, f"sf CLI timed out after {timeout}s"
    except FileNotFoundError:
        return False, "sf CLI not found"
    except Exception as exc:
        return False, f"sf CLI error: {exc}"

    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout).strip()
    return True, proc.stdout


def _get_sf_credentials() -> Optional[Dict[str, str]]:
    """
    Return {'access_token': '...', 'instance_url': '...'} from the
    authenticated sf CLI org, or None on failure.
    """
    ok, out = _run_sf(["sf", "org", "display", "--target-org", SF_ALIAS, "--json"])
    if not ok:
        return None
    try:
        payload = json.loads(out)
        result  = payload.get("result", {})
        token   = result.get("accessToken", "")
        url     = result.get("instanceUrl", "")
        if not token or not url:
            return None
        return {"access_token": token, "instance_url": url.rstrip("/")}
    except Exception:
        return None


# ── REST API client ───────────────────────────────────────────────────────────

class SalesforceREST:
    """
    Minimal Salesforce REST API client backed by a bearer token obtained from
    the authenticated `sf` CLI. Uses `requests` — no additional SFDC libraries
    required beyond what is already in requirements.txt.
    """

    def __init__(self, access_token: str, instance_url: str):
        self.access_token  = access_token
        self.instance_url  = instance_url
        self._session: Any = None

    def _session_get(self) -> Any:
        if self._session is None:
            import requests
            s = requests.Session()
            s.headers.update({
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type":  "application/json",
            })
            self._session = s
        return self._session

    def query(self, soql: str) -> List[Dict]:
        """
        Execute a SOQL query via the REST API, handling pagination automatically.
        Returns a flat list of record dicts.
        """
        session  = self._session_get()
        endpoint = f"{self.instance_url}/services/data/{API_VERSION}/query"
        params   = {"q": soql}
        records: List[Dict] = []

        while True:
            resp = session.get(endpoint, params=params, timeout=60)
            resp.raise_for_status()
            data = resp.json()
            records.extend(data.get("records", []))

            next_url = data.get("nextRecordsUrl")
            if not next_url:
                break
            # Follow pagination
            endpoint = f"{self.instance_url}{next_url}"
            params   = {}

        return records

    @classmethod
    def from_sf_cli(cls) -> Optional["SalesforceREST"]:
        """Build a client using credentials from the authenticated sf CLI."""
        creds = _get_sf_credentials()
        if creds is None:
            return None
        return cls(access_token=creds["access_token"],
                   instance_url=creds["instance_url"])


# ── phone normalisation ───────────────────────────────────────────────────────

def _normalize_phone(raw: str) -> str:
    digits = re.sub(r"\D+", "", raw or "")
    return digits


# ── SOQL builders ─────────────────────────────────────────────────────────────

def _accounts_soql(hours: int, states: List[str]) -> str:
    state_list = ", ".join(f"'{s}'" for s in states)
    # LastModifiedDate filter for live sync; fall back to full pull if hours <= 0
    time_filter = (
        f"AND LastModifiedDate >= LAST_N_HOURS:{hours} " if hours > 0 else ""
    )
    return (
        "SELECT Id, Name, Phone, BillingState, Type, Industry "
        "FROM Account "
        f"WHERE Phone != null "
        f"AND BillingState IN ({state_list}) "
        f"AND IsDeleted = false "
        f"{time_filter}"
        "ORDER BY LastModifiedDate DESC"
    )


def _opportunities_soql(hours: int, states: List[str]) -> str:
    state_list = ", ".join(f"'{s}'" for s in states)
    time_filter = (
        f"AND LastModifiedDate >= LAST_N_HOURS:{hours} " if hours > 0 else ""
    )
    return (
        "SELECT Id, Name, AccountId, Account.Name, Account.BillingState, "
        "StageName, Amount, CloseDate, Probability, "
        "Account.Phone, Account.BillingState "
        "FROM Opportunity "
        f"WHERE Account.BillingState IN ({state_list}) "
        f"AND IsDeleted = false "
        f"{time_filter}"
        "ORDER BY LastModifiedDate DESC"
    )


# ── caller-state update ───────────────────────────────────────────────────────

def _apply_stage_to_caller(
    db: AccountDB,
    sfdc_account_id: str,
    stage: str,
    dry_run: bool,
) -> Optional[str]:
    """
    If the opportunity stage maps to a terminal caller state, update the DB.
    Returns the new status string, or None if no change needed.
    """
    new_status = STAGE_TO_CALLER_STATE.get(stage)
    if not new_status:
        return None
    if dry_run:
        return new_status
    db.update_state_from_opportunity(sfdc_account_id, new_status)
    return new_status


# ── main sync logic ───────────────────────────────────────────────────────────

def sync(
    hours: int = DEFAULT_HOURS,
    states: Optional[List[str]] = None,
    db_path: Optional[str] = None,
    dry_run: bool = False,
    verbose: bool = False,
) -> Dict[str, Any]:
    """
    Pull Accounts + Opportunities from Salesforce updated in the last `hours`
    hours and sync them to the local SQLite DB. Returns a summary dict.

    Summary keys:
      accounts_queried, accounts_inserted, accounts_updated, accounts_skipped,
      opps_queried, opps_inserted, opps_updated,
      state_updates,
      errors
    """
    if states is None:
        states = DEFAULT_STATES

    summary: Dict[str, Any] = {
        "accounts_queried":  0,
        "accounts_inserted": 0,
        "accounts_updated":  0,
        "accounts_skipped":  0,
        "opps_queried":      0,
        "opps_inserted":     0,
        "opps_updated":      0,
        "state_updates":     0,
        "errors":            [],
        "dry_run":           dry_run,
    }

    # ── auth ──────────────────────────────────────────────────────────────────
    sf = SalesforceREST.from_sf_cli()
    if sf is None:
        msg = f"SFDC auth failed for org `{SF_ALIAS}` — re-login required."
        summary["errors"].append(msg)
        _post_slack(f":x: sfdc_live_sync: {msg}")
        return summary

    db = AccountDB(db_path=db_path)

    # ── pull Accounts ─────────────────────────────────────────────────────────
    acc_soql = _accounts_soql(hours, states)
    if verbose:
        print(f"[accounts SOQL] {acc_soql}")
    try:
        accounts = sf.query(acc_soql)
    except Exception as exc:
        msg = f"Account query failed: {exc}"
        summary["errors"].append(msg)
        _post_slack(f":x: sfdc_live_sync: {msg}")
        return summary

    summary["accounts_queried"] = len(accounts)

    for rec in accounts:
        phone    = _normalize_phone(rec.get("Phone") or "")
        name     = (rec.get("Name") or "").strip()
        state    = (rec.get("BillingState") or "").strip().upper()
        vertical = (rec.get("Industry") or rec.get("Type") or "").strip()
        sfdc_id  = (rec.get("Id") or "").strip()

        if not phone or not name:
            summary["accounts_skipped"] += 1
            continue

        if dry_run:
            summary["accounts_skipped"] += 1
            continue

        try:
            status = db.upsert_sfdc_account(
                sfdc_id=sfdc_id,
                name=name,
                phone=phone,
                state=state,
                vertical=vertical,
                sfdc_type=rec.get("Type") or "",
            )
            if status == "inserted":
                summary["accounts_inserted"] += 1
            elif status == "updated":
                summary["accounts_updated"] += 1
            else:
                summary["accounts_skipped"] += 1
        except Exception as exc:
            summary["errors"].append(f"Account upsert error ({name}): {exc}")
            summary["accounts_skipped"] += 1

    # ── pull Opportunities ────────────────────────────────────────────────────
    opp_soql = _opportunities_soql(hours, states)
    if verbose:
        print(f"[opps SOQL] {opp_soql}")
    try:
        opps = sf.query(opp_soql)
    except Exception as exc:
        msg = f"Opportunity query failed: {exc}"
        summary["errors"].append(msg)
        # Not fatal — accounts sync already done
        opps = []

    summary["opps_queried"] = len(opps)

    for rec in opps:
        sfdc_opp_id      = (rec.get("Id") or "").strip()
        opp_name         = (rec.get("Name") or "").strip()
        sfdc_account_id  = (rec.get("AccountId") or "").strip()
        account_info     = rec.get("Account") or {}
        account_name     = (account_info.get("Name") or "").strip()
        stage            = (rec.get("StageName") or "").strip()
        amount           = rec.get("Amount")
        close_date       = (rec.get("CloseDate") or "").strip()
        probability      = rec.get("Probability")
        state            = (account_info.get("BillingState") or "").strip().upper()

        if dry_run:
            summary["opps_updated"] += 1
            # Still report state transitions in dry-run
            new_state = _apply_stage_to_caller(db, sfdc_account_id, stage, dry_run=True)
            if new_state:
                summary["state_updates"] += 1
            continue

        try:
            status = db.upsert_opportunity(
                sfdc_opp_id=sfdc_opp_id,
                opp_name=opp_name,
                sfdc_account_id=sfdc_account_id,
                account_name=account_name,
                stage=stage,
                amount=float(amount) if amount is not None else None,
                close_date=close_date,
                probability=float(probability) if probability is not None else None,
                state=state,
            )
            if status == "inserted":
                summary["opps_inserted"] += 1
            else:
                summary["opps_updated"] += 1
        except Exception as exc:
            summary["errors"].append(f"Opp upsert error ({opp_name}): {exc}")

        # ── update caller state based on stage ────────────────────────────────
        try:
            new_state = _apply_stage_to_caller(db, sfdc_account_id, stage, dry_run=False)
            if new_state:
                summary["state_updates"] += 1
                if verbose:
                    print(f"  state update: {sfdc_account_id} → {new_state} (stage={stage})")
        except Exception as exc:
            summary["errors"].append(f"State update error ({sfdc_opp_id}): {exc}")

    return summary


# ── CLI entrypoint ────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="SFDC live-sync: pull Accounts + Opps updated in last N hours → SQLite"
    )
    parser.add_argument(
        "--hours",
        type=int,
        default=DEFAULT_HOURS,
        help=f"Look-back window in hours (default: {DEFAULT_HOURS})",
    )
    parser.add_argument(
        "--states",
        default=",".join(DEFAULT_STATES),
        help="Comma-separated billing states to sync (default: IA,NE,SD)",
    )
    parser.add_argument(
        "--db",
        default=None,
        help="Override SQLite database path",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Query SFDC but do not write to DB",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print SOQL queries and state transitions",
    )
    args = parser.parse_args()

    states = [s.strip().upper() for s in args.states.split(",") if s.strip()]
    if not states:
        print("ERROR: no states provided", file=sys.stderr)
        return 1

    print(
        f"[sfdc_live_sync] hours={args.hours}  states={states}  "
        f"dry_run={args.dry_run}"
    )

    result = sync(
        hours=args.hours,
        states=states,
        db_path=args.db,
        dry_run=args.dry_run,
        verbose=args.verbose,
    )

    # ── print summary ─────────────────────────────────────────────────────────
    print()
    print("── Accounts ─────────────────────────────────")
    print(f"  queried   : {result['accounts_queried']}")
    print(f"  inserted  : {result['accounts_inserted']}")
    print(f"  updated   : {result['accounts_updated']}")
    print(f"  skipped   : {result['accounts_skipped']}")
    print("── Opportunities ────────────────────────────")
    print(f"  queried   : {result['opps_queried']}")
    print(f"  inserted  : {result['opps_inserted']}")
    print(f"  updated   : {result['opps_updated']}")
    print("── State machine ────────────────────────────")
    print(f"  transitions: {result['state_updates']}")

    if result["errors"]:
        print("── Errors ───────────────────────────────────")
        for e in result["errors"]:
            print(f"  [!] {e}")

    if result["errors"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
