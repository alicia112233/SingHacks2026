"""Human-controlled Telegram alerts for high-urgency TESSERA reviews."""

from __future__ import annotations

import html
import json
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib import error, request


DEFAULT_URGENCY_THRESHOLD = 80
DEFAULT_REMINDER_HOURS = 24
DEFAULT_ESCALATION_DELTA = 5
DEFAULT_ESCALATION_SCORE = 90


class TelegramNotificationError(RuntimeError):
    """Raised when TESSERA cannot deliver a Telegram alert."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _setting_int(name: str, default: int, minimum: int, maximum: int) -> int:
    """Read a bounded integer environment setting without breaking alerts."""

    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        return default
    return min(maximum, max(minimum, value))


def notification_policy() -> dict[str, int]:
    """Return the configurable alert rules, using safe demo defaults."""

    return {
        "threshold": _setting_int("TESSERA_URGENCY_THRESHOLD", DEFAULT_URGENCY_THRESHOLD, 0, 100),
        "reminder_hours": _setting_int("TESSERA_URGENCY_REMINDER_HOURS", DEFAULT_REMINDER_HOURS, 1, 168),
        "escalation_delta": _setting_int("TESSERA_URGENCY_ESCALATION_DELTA", DEFAULT_ESCALATION_DELTA, 1, 100),
        "escalation_score": _setting_int("TESSERA_URGENCY_ESCALATION_SCORE", DEFAULT_ESCALATION_SCORE, 0, 100),
    }


def potential_impact_to_review(client: dict[str, Any], intelligence: dict[str, Any]) -> str:
    """Return one brief, conditional scenario impact suitable for an RM alert.

    The wording deliberately says *illustrative* and *not a forecast*. It avoids
    client names, holdings, account values and free-text RM notes in Telegram.
    """

    client_id = str(client.get("client_id", ""))
    profile = intelligence.get("client_profiles", {}).get(client_id, {})
    scenarios = profile.get("scenarios", []) if isinstance(profile, dict) else []
    candidates = [
        scenario for scenario in scenarios
        if isinstance(scenario, dict) and isinstance(scenario.get("portfolio_impact_pct"), (int, float))
    ]
    if candidates:
        scenario = max(candidates, key=lambda item: abs(float(item["portfolio_impact_pct"])))
        impact = float(scenario["portfolio_impact_pct"])
        return (
            f"Illustrative {scenario.get('name', 'stress')} scenario: "
            f"portfolio impact of {impact:+.1f}%. This is not a forecast."
        )
    return "Controlled evidence indicates a material review priority; impact remains to be verified by the RM."


class TelegramNotifier:
    """Small server-side client for Telegram's sendMessage API."""

    def configuration_status(self) -> str:
        """Return a safe status without exposing any secret values."""

        if os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"):
            return "configured"
        return "not_configured"

    def send_urgency_alert(
        self,
        client: dict[str, Any],
        *,
        kind: str,
        previous_score: int | None,
        potential_impact: str,
    ) -> None:
        """Send an alert requesting human review, never an execution instruction."""

        token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
        if not token or not chat_id:
            raise TelegramNotificationError(
                "Telegram is not configured. Add TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to .env.local."
            )

        client_id = str(client.get("client_id", "")).strip()
        score = client.get("score")
        if not client_id or not isinstance(score, (int, float)):
            raise TelegramNotificationError("Urgency alert is missing a valid client reference or score.")

        heading = {
            "initial": "urgency alert",
            "reminder": "review reminder",
            "escalation": "urgency escalated",
        }.get(kind, "urgency alert")
        score_line = f"Urgency score: <b>{int(score)}/100</b>"
        if kind == "escalation" and previous_score is not None:
            score_line += f" (was {previous_score}/100)"
        message = (
            f"<b>TESSERA • {heading}</b>\n\n"
            f"Client reference: <code>{html.escape(client_id)}</code>\n"
            f"{score_line}\n"
            f"Potential impact to review: {html.escape(potential_impact)}\n"
            f"Next step: {html.escape(str(client.get('next_step', 'Open TESSERA and review the evidence.')))}\n\n"
            "RM review is required. This is not a forecast and does not approve a trade or client action."
        )
        payload = json.dumps(
            {
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }
        ).encode("utf-8")
        telegram_request = request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with request.urlopen(telegram_request, timeout=10) as response:
                result = json.loads(response.read().decode("utf-8"))
        except (OSError, error.URLError, json.JSONDecodeError) as exc:
            raise TelegramNotificationError("Telegram could not accept the alert.") from exc

        if not isinstance(result, dict) or result.get("ok") is not True:
            raise TelegramNotificationError("Telegram could not accept the alert.")


class UrgencyAlertStore:
    """Local persistent state for reminders and escalation alerts."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()

    def _read_unlocked(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if isinstance(payload, dict) and isinstance(payload.get("clients"), dict):
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

    def save(self, client_id: str, state: dict[str, Any]) -> None:
        with self._lock:
            records = self._read_unlocked()
            records[client_id] = state
            self._write_unlocked(records)


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

    def save(self, client_id: str, state: dict[str, Any]) -> None:
        self._ensure_schema()
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO tessera_urgency_alert_state (client_id, state, updated_at)
                VALUES (%s, %s::jsonb, NOW())
                ON CONFLICT (client_id) DO UPDATE
                SET state = EXCLUDED.state, updated_at = NOW()
                """,
                (client_id, json.dumps(state)),
            )


def production_urgency_alert_store() -> PostgresUrgencyAlertStore:
    """Return a durable store; a temporary serverless file would duplicate alerts."""

    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for scheduled production urgency alerts.")
    return PostgresUrgencyAlertStore(database_url)


def acknowledge_urgency_alert(
    alert_store: Any, client_id: str, note: str = ""
) -> dict[str, Any]:
    """Pause reminders while preserving the state needed for escalation alerts."""

    existing = alert_store.get(client_id)
    if existing is None:
        raise ValueError("No urgency alert exists for this client yet.")
    timestamp = _now().isoformat()
    existing.update(
        {
            "status": "acknowledged",
            "acknowledged_at": timestamp,
            "acknowledgement_note": note[:500],
            "last_checked_at": timestamp,
        }
    )
    alert_store.save(client_id, existing)
    return existing


def _fresh_state(client_id: str, score: int, timestamp: str) -> dict[str, Any]:
    return {
        "client_id": client_id,
        "status": "open",
        "first_alert_at": timestamp,
        "last_alert_at": timestamp,
        "last_checked_at": timestamp,
        "last_score": score,
        "last_alert_score": score,
        "last_alert_kind": "initial",
    }


def scan_urgency_alerts(
    intelligence: dict[str, Any],
    alert_store: Any,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Send initial, reminder, or escalation alerts using durable case state."""

    policy = notification_policy()
    queue = intelligence.get("book", {}).get("priority_queue", [])
    if not isinstance(queue, list):
        raise ValueError("Priority queue is unavailable.")

    current_time = now or _now()
    timestamp = current_time.isoformat()
    notifier = TelegramNotifier()
    result: dict[str, Any] = {
        "status": "completed",
        "policy": policy,
        "qualified": 0,
        "initial": [],
        "reminded": [],
        "escalated": [],
        "acknowledged": [],
        "below_threshold": [],
    }

    for client in queue:
        if not isinstance(client, dict):
            continue
        client_id = str(client.get("client_id", "")).strip()
        score = client.get("score")
        if not client_id or not isinstance(score, (int, float)):
            continue
        score = int(score)
        existing = alert_store.get(client_id)

        if score < policy["threshold"]:
            if existing:
                existing.update({"status": "below_threshold", "last_score": score, "last_checked_at": timestamp})
                alert_store.save(client_id, existing)
            result["below_threshold"].append(client_id)
            continue

        result["qualified"] += 1
        state = existing or {}
        prior_alert_score = state.get("last_alert_score")
        prior_alert_score = int(prior_alert_score) if isinstance(prior_alert_score, (int, float)) else None
        last_alert_at = _as_utc(str(state.get("last_alert_at", "")))
        status = str(state.get("status", "open"))
        kind: str | None = None

        if not existing or status == "below_threshold":
            kind = "initial"
        elif (
            prior_alert_score is not None
            and (
                score >= policy["escalation_score"] > prior_alert_score
                or score >= prior_alert_score + policy["escalation_delta"]
            )
        ):
            kind = "escalation"
        elif status == "open" and (
            last_alert_at is None
            or current_time - last_alert_at >= timedelta(hours=policy["reminder_hours"])
        ):
            kind = "reminder"

        if kind:
            notifier.send_urgency_alert(
                client,
                kind=kind,
                previous_score=prior_alert_score,
                potential_impact=potential_impact_to_review(client, intelligence),
            )
            if kind == "initial":
                state = _fresh_state(client_id, score, timestamp)
            else:
                state.update(
                    {
                        "status": "open" if kind == "escalation" else status,
                        "last_alert_at": timestamp,
                        "last_checked_at": timestamp,
                        "last_score": score,
                        "last_alert_score": score,
                        "last_alert_kind": kind,
                    }
                )
            alert_store.save(client_id, state)
            result[{"initial": "initial", "reminder": "reminded", "escalation": "escalated"}[kind]].append(client_id)
        else:
            state.update({"last_score": score, "last_checked_at": timestamp})
            alert_store.save(client_id, state)
            if status == "acknowledged":
                result["acknowledged"].append(client_id)

    return result
