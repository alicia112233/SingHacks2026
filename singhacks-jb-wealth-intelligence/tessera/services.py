"""Shared application services for local and serverless HTTP entry points."""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from tessera.engine import build_intelligence_payload, generate_alternative_recommendation
from tessera.market_news import refresh as refresh_market_news
from tessera.notifications import scan_urgency_alerts
from tessera.review_state import reviewed_snapshot, reviewed_intelligence, requested_action


MAX_REQUEST_BYTES = 8_192
ALLOWED_DECISIONS = {"approved", "dismissed", "edited", "pending"}


class IntelligenceService:
    """Cache analytics until one of the controlled source files changes."""

    def __init__(self, data_dir: Path, live_events_path: Path | None = None):
        self.data_dir = data_dir
        self.live_events_path = live_events_path or data_dir.parent / "runtime" / "live_events.json"
        self._lock = threading.Lock()
        self._signature: tuple[tuple[str, int, int], ...] | None = None
        self._payload: dict[str, Any] | None = None

    def _source_signature(self) -> tuple[tuple[str, int, int], ...]:
        files = sorted((*self.data_dir.glob("*.csv"), *self.data_dir.glob("*.json")))
        if self.live_events_path.exists():
            files.append(self.live_events_path)
        return tuple(
            (path.name, path.stat().st_mtime_ns, path.stat().st_size) for path in files
        )

    def get(self) -> dict[str, Any]:
        if os.environ.get("TESSERA_MODE", "demo").strip().lower() != "demo":
            raise RuntimeError("TESSERA supports demo mode only. Production use requires authenticated identities and client-level authorization.")
        signature = self._source_signature()
        with self._lock:
            if self._payload is None or signature != self._signature:
                self._payload = build_intelligence_payload(self.data_dir, self.live_events_path)
                self._signature = signature
            return self._payload


class DecisionStoreProtocol(Protocol):
    def snapshot(self) -> dict[str, Any]: ...

    def append(self, record: dict[str, Any]) -> dict[str, Any]: ...

    def transact(self, create_record): ...


def effective_decisions(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Resolve the most recently recorded state of each recommendation."""

    return {record["recommendation_id"]: record for record in records if record.get("action") in ALLOWED_DECISIONS}


class DecisionStore:
    """Thread-safe local decision ledger used by the development server."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()

    def _read_unlocked(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        with self.path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, list):
            raise ValueError("Decision ledger must contain a JSON array")
        return payload

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            records = self._read_unlocked()
        return {"records": records, "effective": effective_decisions(records)}

    def append(self, record):
        return self.transact(lambda _records: record)

    def transact(self, create_record):
        with self._lock:
            records = self._read_unlocked()
            record = create_record(records)
            records.append(record)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            with temporary.open("w", encoding="utf-8") as handle:
                json.dump(records, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            temporary.replace(self.path)
        return {"record": record, "records": records, "effective": effective_decisions(records)}


class PostgresDecisionStore:
    """Append-only decision ledger for production deployments."""

    def __init__(self, database_url: str):
        if not database_url:
            raise ValueError("DATABASE_URL is required")
        self.database_url = database_url
        self._schema_lock = threading.Lock()
        self._schema_ready = False

    def _connect(self):
        import psycopg

        return psycopg.connect(self.database_url, connect_timeout=8)

    def _ensure_schema(self) -> None:
        if self._schema_ready:
            return
        with self._schema_lock:
            if self._schema_ready:
                return
            with self._connect() as connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS tessera_decision_events (
                        id UUID PRIMARY KEY,
                        recommendation_id TEXT NOT NULL,
                        client_id TEXT NOT NULL,
                        client_name TEXT NOT NULL,
                        recommendation_index INTEGER NOT NULL CHECK (recommendation_index >= 0),
                        recommendation_title TEXT NOT NULL,
                        action TEXT NOT NULL CHECK (action IN ('approved', 'dismissed', 'edited', 'pending')),
                        note TEXT NOT NULL DEFAULT '',
                        actor TEXT NOT NULL,
                        recorded_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS tessera_decision_events_recommendation_time
                    ON tessera_decision_events (recommendation_id, recorded_at, id)
                    """
                )
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS tessera_review_events (
                        id UUID PRIMARY KEY,
                        payload JSONB NOT NULL,
                        recorded_at TIMESTAMPTZ NOT NULL
                    )
                """)
            self._schema_ready = True

    @staticmethod
    def _record(row: tuple[Any, ...]) -> dict[str, Any]:
        return {
            "id": str(row[0]),
            "recommendation_id": row[1],
            "client_id": row[2],
            "client_name": row[3],
            "recommendation_index": row[4],
            "recommendation_title": row[5],
            "action": row[6],
            "note": row[7],
            "actor": row[8],
            "recorded_at": row[9].isoformat(),
        }

    def _records(self, connection) -> list[dict[str, Any]]:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, recommendation_id, client_id, client_name,
                       recommendation_index, recommendation_title, action,
                       note, actor, recorded_at
                FROM tessera_decision_events
                ORDER BY recorded_at, id
                """
            )
            records = [self._record(row) for row in cursor.fetchall()]
            cursor.execute("SELECT payload FROM tessera_review_events ORDER BY recorded_at, id")
            records.extend(row[0] for row in cursor.fetchall())
            return sorted(records, key=lambda r: (r["recorded_at"], r["id"]))

    def snapshot(self) -> dict[str, Any]:
        self._ensure_schema()
        with self._connect() as connection:
            records = self._records(connection)
        return {"records": records, "effective": effective_decisions(records)}

    def append(self, record):
        return self.transact(lambda _records: record)

    def transact(self, create_record):
        from psycopg.types.json import Jsonb

        self._ensure_schema()
        with self._connect() as connection:
            with connection.cursor() as cursor:
                # Serialize checks and writes across serverless workers.
                cursor.execute("SELECT pg_advisory_xact_lock(81642017)")
                records = self._records(connection)
                record = create_record(records)
                cursor.execute(
                    "INSERT INTO tessera_review_events (id, payload, recorded_at) VALUES (%s, %s, %s)",
                    (record["id"], Jsonb(record), record["recorded_at"]),
                )
                records.append(record)
        return {"record": record, "records": records, "effective": effective_decisions(records)}


def production_decision_store() -> PostgresDecisionStore:
    """Return the production store, failing clearly when storage is not configured."""

    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError(
            "Decision storage is not configured. Add DATABASE_URL to the Vercel project."
        )
    return PostgresDecisionStore(database_url)


def _event(client, index, recommendation_data, action, **fields):
    return {
        "id": str(uuid.uuid4()), "recommendation_id": recommendation_data["id"],
        "version": recommendation_data["version"], "client_id": client["client_id"],
        "client_name": client["name"], "recommendation_index": index,
        "recommendation_title": recommendation_data["title"], "action": action,
        "recorded_at": datetime.now(timezone.utc).isoformat(), **fields,
    }


def create_decision_record(body, intelligence, decision_records=None):
    reviewed = reviewed_intelligence(intelligence, {"records": decision_records or []})
    client, index, recommendation = requested_action(body, reviewed)
    action = str(body.get("action", "")).lower()
    note = str(body.get("note", "")).strip()
    if action not in ALLOWED_DECISIONS:
        raise ValueError("Unsupported decision")
    if len(note) > 1000:
        raise ValueError("Note must be 1,000 characters or fewer")
    if action == "edited" and not note:
        raise ValueError("Revised action wording is required")
    if action == "approved":
        if len(note) < 10:
            raise ValueError("State the action taken before approving (at least 10 characters)")
        validation = recommendation.get("risk_validation", {})
        if validation.get("score", 0) < 50 or validation.get("blockers"):
            raise ValueError("Blocked recommendations cannot be approved; resolve validation failures first")
    return _event(client, index, recommendation, action, note=note, actor=intelligence["meta"]["rm"])


def record_decision(body, intelligence, store):
    snapshot = store.transact(lambda records: create_decision_record(body, intelligence, records))
    return reviewed_snapshot(snapshot, intelligence)


def create_alternative_recommendation(body, intelligence, decision_records=None):
    reviewed = reviewed_intelligence(intelligence, {"records": decision_records or []})
    client, index, _action = requested_action(body, reviewed, "dismissed_index")
    return generate_alternative_recommendation(reviewed, client["client_id"], index, decision_records)


def record_alternative(body, intelligence, store):
    def create(records):
        reviewed = reviewed_intelligence(intelligence, {"records": records})
        client, index, original = requested_action(body, reviewed, "dismissed_index")
        selected = generate_alternative_recommendation(reviewed, client["client_id"], index, records)
        from tessera.review_state import action_version
        action = selected["recommendation"]
        action["version"] = action_version(action)
        return _event(client, selected["index"], action, "alternative", recommendation=action, replacement_for=original["title"])
    snapshot = store.transact(create)
    event = snapshot["record"]
    return {"index": event["recommendation_index"], "recommendation": event["recommendation"], "decisions": reviewed_snapshot(snapshot, intelligence)}


def record_evaluation(body, intelligence, store):
    from tessera.evaluation import evaluate_recommendation

    snapshot = store.snapshot()
    reviewed = reviewed_intelligence(intelligence, snapshot)
    client, index, action = requested_action(body, reviewed)
    # Evaluate this version's deterministic assessment, not a previous panel cap.
    baseline_records = [r for r in snapshot["records"] if r.get("action") != "evaluated"]
    baseline = reviewed_intelligence(intelligence, {"records": baseline_records})
    evaluation = evaluate_recommendation(baseline, client["client_id"], index)
    def create(records):
        current = reviewed_intelligence(intelligence, {"records": records})
        current_client, current_index, current_action = requested_action(body, current)
        return _event(current_client, current_index, current_action, "evaluated", evaluation=evaluation)
    saved = store.transact(create)
    decisions = reviewed_snapshot(saved, intelligence)
    applied = decisions["reviews"][f"{client['client_id']}:{index}"]["risk_validation"]
    consensus = evaluation["consensus"]
    if applied["score"] < consensus["score"]:
        consensus = {**consensus, "score": applied["score"], "band": applied["band"], "rule": "An earlier persisted panel restriction remains in force. A retry without completed judges cannot clear it."}
    return {**evaluation, "consensus": consensus, "decisions": decisions}


def create_escalation_review(body, intelligence):
    if not isinstance(body, dict):
        raise ValueError("Request body must be an object")
    decision = str(body.get("decision", "")).lower()
    if decision not in {"confirmed", "dismissed"}:
        raise ValueError("Decision must be confirmed or dismissed")
    card = next((c for c in intelligence["book"]["priority_queue"] if c["client_id"] == str(body.get("client_id", ""))), None)
    if not card:
        raise ValueError("Unknown client")
    escalation = card.get("escalation")
    if not escalation or escalation.get("id") != body.get("escalation_id"):
        raise ValueError("This exposure flag has changed. Refresh the review before continuing.")
    note = str(body.get("note", "")).strip()
    if len(note) > 1000:
        raise ValueError("Note must be 1,000 characters or fewer")
    return {
        "id": str(uuid.uuid4()), "action": f"escalation_{decision}", "client_id": card["client_id"],
        "client_name": card["client_name"], "escalation_id": escalation["id"], "kind": escalation["kind"],
        "headline": escalation["headline"], "reason": escalation["reason"], "note": note,
        "actor": intelligence["meta"]["rm"], "recorded_at": datetime.now(timezone.utc).isoformat(),
    }


def record_escalation_review(body, intelligence, store):
    """Record whether the RM confirmed or dismissed a news breach alert."""
    snapshot = store.transact(lambda _records: create_escalation_review(body, intelligence))
    return {"record": snapshot["record"], **review_context(intelligence, store)}


def review_context(intelligence, store):
    """Read one ledger snapshot for the displayed actions and their decisions."""
    snapshot = store.snapshot()
    return {"intelligence": reviewed_intelligence(intelligence, snapshot),
            "decisions": reviewed_snapshot(snapshot, intelligence)}


def refresh_market_intelligence(data_dir, live_events_path, intelligence_provider, alert_store_factory):
    """Return refreshed evidence even when the independent notification step fails."""
    result = refresh_market_news(data_dir, live_events_path)
    result["intelligence"] = intelligence_provider()
    try:
        result["urgency_alerts"] = scan_urgency_alerts(result["intelligence"], alert_store_factory())
    except Exception:
        logging.getLogger(__name__).warning("News refreshed, but urgency notifications are unavailable", exc_info=True)
        result["urgency_alerts"] = {"status": "unavailable", "reason": "News refreshed successfully; urgency notification delivery could not be confirmed."}
    return result
