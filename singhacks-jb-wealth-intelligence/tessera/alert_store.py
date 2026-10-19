"""Persistent alert state and atomic updates for local and hosted deployments."""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any


class UrgencyAlertStore:
    """Local persistent state for reminders and escalation alerts."""

    _locks = {}
    _locks_guard = threading.Lock()

    def __init__(self, path: Path):
        self.path = path
        with self._locks_guard:
            self._lock = self._locks.setdefault(path.resolve(), threading.RLock())

    def _read_unlocked(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError("Alert state could not be read; refusing to resend from an empty ledger") from error
        if not isinstance(payload, dict) or ("clients" in payload and not isinstance(payload["clients"], dict)):
            raise ValueError("Alert state has an invalid structure; refusing to resend from an empty ledger")
        if isinstance(payload.get("clients"), dict):
            return payload["clients"]
        # Version-one alert files only recorded that a message was sent. Treat
        # them as legacy data so a new, controlled alert lifecycle can begin.
        return {}

    def _write_unlocked(self, records: dict[str, dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps({"version": 2, "clients": records}, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)

    def get(self, client_id: str) -> dict[str, Any] | None:
        with self._lock:
            record = self._read_unlocked().get(client_id)
            return dict(record) if isinstance(record, dict) else None

    def save(self, client_id, state):
        self.transact(client_id, lambda _current: (state, None))

    def transact(self, client_id, update):
        """Serialize the read, delivery decision and write in the local process."""
        with self._lock:
            records = self._read_unlocked()
            state, result = update(records.get(client_id))
            if state is not None:
                records[client_id] = state
                self._write_unlocked(records)
            return result


class PostgresUrgencyAlertStore:
    """Durable alert state for production and Vercel Cron runs."""

    def __init__(self, database_url: str):
        if not database_url:
            raise ValueError("DATABASE_URL is required for production urgency alerts")
        self.database_url = database_url
        self._schema_ready = False
        self._schema_lock = threading.Lock()

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
                    CREATE TABLE IF NOT EXISTS tessera_urgency_alert_state (
                        client_id TEXT PRIMARY KEY,
                        state JSONB NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
            self._schema_ready = True

    def get(self, client_id: str) -> dict[str, Any] | None:
        self._ensure_schema()
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT state FROM tessera_urgency_alert_state WHERE client_id = %s",
                (client_id,),
            )
            row = cursor.fetchone()
        return dict(row[0]) if row and isinstance(row[0], dict) else None

    def save(self, client_id, state):
        self.transact(client_id, lambda _current: (state, None))

    def transact(self, client_id, update):
        self._ensure_schema()
        with self._connect() as connection, connection.cursor() as cursor:
            # The client lock also covers the first alert, when no row exists.
            cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", ("tessera-alert:" + client_id,))
            cursor.execute("SELECT state FROM tessera_urgency_alert_state WHERE client_id = %s", (client_id,))
            row = cursor.fetchone()
            state, result = update(dict(row[0]) if row else None)
            if state is not None:
                cursor.execute(
                    """INSERT INTO tessera_urgency_alert_state (client_id, state, updated_at)
                       VALUES (%s, %s::jsonb, NOW())
                       ON CONFLICT (client_id) DO UPDATE SET state = EXCLUDED.state, updated_at = NOW()""",
                    (client_id, json.dumps(state)),
                )
        return result


def production_urgency_alert_store() -> PostgresUrgencyAlertStore:
    """Return a durable store; a temporary serverless file would duplicate alerts."""

    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for scheduled production urgency alerts.")
    return PostgresUrgencyAlertStore(database_url)


