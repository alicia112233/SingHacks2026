"""Durable, server-only backend files in the project's existing PostgreSQL store."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import threading
import uuid
from pathlib import Path


LIVE_EVENTS_KEY = "market/live_events.json"


def json_bytes(value) -> bytes:
    return json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=True,
                      separators=(",", ":"), default=str).encode("utf-8")


def merge_events(existing, incoming):
    """Union independently fetched registers without losing another worker's news."""
    by_id = {event["event_id"]: dict(event) for event in existing}
    for event in incoming:
        event_id = event["event_id"]
        previous = by_id.get(event_id, {})
        merged = {**previous, **event}
        if previous.get("retrieved_at"):
            merged["retrieved_at"] = previous["retrieved_at"]
        by_id[event_id] = merged
    return sorted(by_id.values(), key=lambda event: (event.get("event_date", ""), event["event_id"]))


def mirror_events(path: Path, events) -> None:
    """Keep an atomic disposable mirror for the calculation engine's file reader."""
    content = json_bytes(events)
    if path.exists() and path.read_bytes() == content:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temporary.write_bytes(content)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


class PostgresOutputStore:
    def __init__(self, database_url: str):
        if not database_url:
            raise ValueError("DATABASE_URL is required for cloud backend outputs")
        self.database_url = database_url
        self._schema_ready = False
        self._schema_lock = threading.Lock()

    def _connect(self):
        import psycopg
        return psycopg.connect(self.database_url, connect_timeout=8)

    def ensure_schema(self):
        if self._schema_ready:
            return
        with self._schema_lock:
            if self._schema_ready:
                return
            with self._connect() as connection, connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_xact_lock(81642018)")
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS tessera_backend_outputs (
                        key TEXT PRIMARY KEY,
                        content BYTEA NOT NULL,
                        content_type TEXT NOT NULL,
                        sha256 TEXT NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                """)
            self._schema_ready = True

    @staticmethod
    def _put(cursor, key, content, content_type):
        digest = hashlib.sha256(content).hexdigest()
        cursor.execute("""
            INSERT INTO tessera_backend_outputs (key, content, content_type, sha256)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (key) DO UPDATE SET content = EXCLUDED.content,
                content_type = EXCLUDED.content_type, sha256 = EXCLUDED.sha256,
                updated_at = NOW()
            WHERE tessera_backend_outputs.sha256 <> EXCLUDED.sha256
        """, (key, content, content_type, digest))
        return digest

    def put(self, key, content: bytes, content_type="application/octet-stream"):
        self.ensure_schema()
        with self._connect() as connection, connection.cursor() as cursor:
            return self._put(cursor, key, content, content_type)

    def put_json(self, key, value):
        return self.put(key, json_bytes(value), "application/json")

    def read(self, key):
        self.ensure_schema()
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT content FROM tessera_backend_outputs WHERE key = %s", (key,))
            row = cursor.fetchone()
        return bytes(row[0]) if row else None

    def read_json(self, key, default=None):
        content = self.read(key)
        return json.loads(content) if content is not None else default

    def merge_market_events(self, incoming):
        self.ensure_schema()
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(81642019)")
            cursor.execute("SELECT content FROM tessera_backend_outputs WHERE key = %s", (LIVE_EVENTS_KEY,))
            row = cursor.fetchone()
            events = merge_events(json.loads(bytes(row[0])) if row else [], incoming)
            self._put(cursor, LIVE_EVENTS_KEY, json_bytes(events), "application/json")
        return events

    def upload_file(self, key, path: Path):
        return self.put(key, path.read_bytes(), mimetypes.guess_type(path.name)[0] or "application/octet-stream")

    def inventory(self):
        self.ensure_schema()
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("""SELECT key, content_type, octet_length(content), sha256, updated_at
                              FROM tessera_backend_outputs ORDER BY key""")
            return [{"key": row[0], "content_type": row[1], "bytes": row[2],
                     "sha256": row[3], "updated_at": row[4].isoformat()} for row in cursor.fetchall()]


def production_output_store():
    return PostgresOutputStore(os.environ.get("DATABASE_URL", "").strip())
