"""Shared application services for local and serverless HTTP entry points."""

from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from tessera.engine import build_intelligence_payload


MAX_REQUEST_BYTES = 8_192
ALLOWED_DECISIONS = {"approved", "dismissed", "edited", "pending"}


class IntelligenceService:
    """Cache analytics until one of the controlled source files changes."""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self._lock = threading.Lock()
        self._signature: tuple[tuple[str, int, int], ...] | None = None
        self._payload: dict[str, Any] | None = None

    def _source_signature(self) -> tuple[tuple[str, int, int], ...]:
        files = sorted((*self.data_dir.glob("*.csv"), *self.data_dir.glob("*.json")))
        return tuple(
            (path.name, path.stat().st_mtime_ns, path.stat().st_size) for path in files
        )

    def get(self) -> dict[str, Any]:
        signature = self._source_signature()
        with self._lock:
            if self._payload is None or signature != self._signature:
                self._payload = build_intelligence_payload(self.data_dir)
                self._signature = signature
            return self._payload


class DecisionStoreProtocol(Protocol):
    def snapshot(self) -> dict[str, Any]: ...

    def append(self, record: dict[str, Any]) -> dict[str, Any]: ...


def effective_decisions(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Resolve the most recently recorded state of each recommendation."""

    return {record["recommendation_id"]: record for record in records}


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

    def append(self, record: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            records = self._read_unlocked()
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
            return [self._record(row) for row in cursor.fetchall()]

    def snapshot(self) -> dict[str, Any]:
        self._ensure_schema()
        with self._connect() as connection:
            records = self._records(connection)
        return {"records": records, "effective": effective_decisions(records)}

    def append(self, record: dict[str, Any]) -> dict[str, Any]:
        self._ensure_schema()
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO tessera_decision_events (
                        id, recommendation_id, client_id, client_name,
                        recommendation_index, recommendation_title, action,
                        note, actor, recorded_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        record["id"], record["recommendation_id"], record["client_id"],
                        record["client_name"], record["recommendation_index"],
                        record["recommendation_title"], record["action"], record["note"],
                        record["actor"], record["recorded_at"],
                    ),
                )
            records = self._records(connection)
        return {"record": record, "records": records, "effective": effective_decisions(records)}


def production_decision_store() -> PostgresDecisionStore:
    """Return the production store, failing clearly when storage is not configured."""

    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError(
            "Decision storage is not configured. Add DATABASE_URL to the Vercel project."
        )
    return PostgresDecisionStore(database_url)


def create_decision_record(
    body: Any, intelligence: dict[str, Any]
) -> dict[str, Any]:
    """Validate an action request against current source-backed recommendations."""

    if not isinstance(body, dict):
        raise ValueError("Request body must be an object")

    client_id = str(body.get("client_id", ""))
    try:
        recommendation_index = int(body.get("recommendation_index", -1))
    except (TypeError, ValueError) as error:
        raise ValueError("Unknown recommendation") from error
    action = str(body.get("action", "")).lower()
    note = str(body.get("note", "")).strip()

    # Decisions can be made from every review room, not only the three clients
    # selected for the dashboard's featured section.
    client = intelligence.get("client_profiles", {}).get(client_id)
    if client is None:
        client = intelligence.get("featured_clients", {}).get(client_id)
    if client is None:
        raise ValueError("Unknown client")
    if recommendation_index < 0 or recommendation_index >= len(client["recommendations"]):
        raise ValueError("Unknown recommendation")
    if action not in ALLOWED_DECISIONS:
        raise ValueError("Unsupported decision")
    if len(note) > 1_000:
        raise ValueError("Note must be 1,000 characters or fewer")
    if action == "approved" and len(note) < 10:
        raise ValueError("State the action taken before approving (at least 10 characters)")

    recommendation = client["recommendations"][recommendation_index]
    validation = recommendation.get("risk_validation", {})
    if action == "approved" and (
        validation.get("blockers") or int(validation.get("score", 100)) < 50
    ):
        raise ValueError(
            "Blocked recommendations cannot be approved; resolve the hard-stop controls first"
        )
    return {
        "id": str(uuid.uuid4()),
        "recommendation_id": f"{client_id}:{recommendation_index}",
        "client_id": client_id,
        "client_name": client["name"],
        "recommendation_index": recommendation_index,
        "recommendation_title": recommendation["title"],
        "action": action,
        "note": note,
        "actor": intelligence["meta"]["rm"],
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
