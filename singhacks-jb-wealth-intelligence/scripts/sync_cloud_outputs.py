"""Backfill backend files and local ledgers into the existing cloud database.

Defaults to a dry run. Use --upload to write, or --inventory to list cloud files.
Secrets and frontend screenshots are deliberately excluded from the file set.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import load_local_environment
from tessera.alert_store import PostgresUrgencyAlertStore
from tessera.cloud_outputs import LIVE_EVENTS_KEY, production_output_store
from tessera.services import IntelligenceService, PostgresDecisionStore, review_context


def backend_files():
    paths = set()
    for directory in (ROOT / "data", ROOT / "runtime", ROOT / "outputs"):
        if directory.exists():
            paths.update(path for path in directory.rglob("*")
                         if path.is_file() and path.name != "cloud-output-inventory.json"
                         and path.suffix.lower() in {".csv", ".json", ".md", ".txt"})
    paths.update((ROOT / "docs").glob("CHAT_EVALUATION_RESULTS.*"))
    paths.update((ROOT / "web" / "data").glob("*.json"))
    paths.update((ROOT / "site" / "data").glob("*.json"))
    return sorted(paths)


def import_decisions(store, records):
    """Keep original IDs, timestamps and evidence versions; never replay an action."""
    from psycopg.types.json import Jsonb
    for record in records:
        UUID(record["id"])
        datetime.fromisoformat(record["recorded_at"])
        if not record.get("client_id") or not record.get("action"):
            raise ValueError("A local decision lacks its client or action")
    store._ensure_schema()
    imported = 0
    with store._connect() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(81642017)")
        for record in records:
            cursor.execute("""
                INSERT INTO tessera_review_events (id, payload, recorded_at)
                SELECT %s, %s, %s WHERE NOT EXISTS
                    (SELECT 1 FROM tessera_decision_events WHERE id = %s)
                ON CONFLICT (id) DO NOTHING
            """, (record["id"], Jsonb(record), record["recorded_at"], record["id"]))
            imported += cursor.rowcount
    return imported


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upload", action="store_true")
    parser.add_argument("--inventory", action="store_true")
    args = parser.parse_args()
    load_local_environment()
    files = backend_files()
    if not args.upload and not args.inventory:
        print(f"Dry run: {len(files)} backend files, {sum(p.stat().st_size for p in files):,} bytes")
        for path in files:
            print(path.relative_to(ROOT).as_posix())
        return
    outputs = production_output_store()
    if args.upload:
        decisions = PostgresDecisionStore(os.environ["DATABASE_URL"])
        if outputs.read("migration/preexisting-cloud-decisions.json") is None:
            outputs.put_json("migration/preexisting-cloud-decisions.json", decisions.snapshot())
        for path in files:
            key = "files/" + path.relative_to(ROOT).as_posix()
            digest = outputs.upload_file(key, path)
            if hashlib.sha256(outputs.read(key)).hexdigest() != digest:
                raise RuntimeError(f"Cloud readback failed for {key}")
        events_path = ROOT / "runtime" / "live_events.json"
        local_events = json.loads(events_path.read_text(encoding="utf-8")) if events_path.exists() else []
        events = outputs.merge_market_events(local_events)
        local_ledger = ROOT / "runtime" / "decisions.json"
        records = json.loads(local_ledger.read_text(encoding="utf-8")) if local_ledger.exists() else []
        imported = import_decisions(decisions, records)
        alerts = PostgresUrgencyAlertStore(os.environ["DATABASE_URL"])
        alerts._ensure_schema()
        alert_file = ROOT / "runtime" / "telegram_urgency_alerts.json"
        if alert_file.exists():
            state = json.loads(alert_file.read_text(encoding="utf-8"))
            if state.get("version") == 2:
                for client_id, alert in state.get("clients", {}).items():
                    alerts.transact(client_id, lambda current, incoming=alert: (current or incoming, None))
        intelligence = IntelligenceService(ROOT / "data", output_store=outputs).get()
        outputs.put_json("review/current.json", review_context(intelligence, decisions))
        print(f"Verified {len(files)} uploaded files; {len(events)} shared news events; {imported} new decision records")
        print(f"Cloud ledger: {len(decisions.snapshot()['records'])} total records")
    inventory = outputs.inventory()
    print(f"Cloud backend outputs: {len(inventory)} files, {sum(p['bytes'] for p in inventory):,} bytes")
    report = ROOT / "runtime" / "cloud-output-inventory.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
    print(f"Inventory: {report}")


if __name__ == "__main__":
    main()
