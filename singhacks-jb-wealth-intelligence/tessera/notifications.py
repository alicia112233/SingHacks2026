"""Telegram alerts for human review of high-urgency TESSERA cases.

The notifier never sends a recommendation to a client and never executes a
trade.  It only asks the Relationship Manager to open TESSERA and review a
case that has crossed the configured urgency threshold.
"""

from __future__ import annotations

import html
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, request


DEFAULT_URGENCY_THRESHOLD = 80


class TelegramNotificationError(RuntimeError):
    """Raised when TESSERA cannot deliver a Telegram alert."""


class TelegramNotifier:
    """Small server-side client for Telegram's sendMessage API."""

    def configuration_status(self) -> str:
        """Return a safe status without exposing any secret values."""

        if os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"):
            return "configured"
        return "not_configured"

    def send_urgency_alert(self, client: dict[str, Any]) -> None:
        """Send one human-review alert for a validated priority-queue client."""

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

        next_step = str(client.get("next_step", "Open TESSERA and review the evidence.")).strip()
        message = (
            "<b>TESSERA • urgency alert</b>\n\n"
            f"Client reference: <code>{html.escape(client_id)}</code>\n"
            f"Urgency score: <b>{int(score)}%</b>\n"
            f"Next step: {html.escape(next_step)}\n\n"
            "Relationship Manager review is required. This alert does not approve a trade or client action."
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
    """Local, persistent record that prevents duplicate demo alerts."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()

    def _read_unlocked(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def was_sent(self, alert_key: str) -> bool:
        with self._lock:
            return alert_key in self._read_unlocked()

    def mark_sent(self, alert_key: str, client_id: str, score: int) -> None:
        with self._lock:
            records = self._read_unlocked()
            records[alert_key] = {
                "client_id": client_id,
                "score": score,
                "sent_at": datetime.now(timezone.utc).isoformat(),
            }
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
            temporary.replace(self.path)


def scan_urgency_alerts(
    intelligence: dict[str, Any],
    alert_store: UrgencyAlertStore,
    threshold: int = DEFAULT_URGENCY_THRESHOLD,
) -> dict[str, Any]:
    """Alert once per client and data snapshot when score is at least threshold."""

    if threshold < 0 or threshold > 100:
        raise ValueError("Urgency threshold must be between 0 and 100.")

    queue = intelligence.get("book", {}).get("priority_queue", [])
    as_of = str(intelligence.get("meta", {}).get("as_of", "unknown"))
    if not isinstance(queue, list):
        raise ValueError("Priority queue is unavailable.")

    notifier = TelegramNotifier()
    sent: list[str] = []
    already_alerted: list[str] = []
    qualified = 0
    for client in queue:
        if not isinstance(client, dict):
            continue
        client_id = str(client.get("client_id", "")).strip()
        score = client.get("score")
        if not client_id or not isinstance(score, (int, float)) or score < threshold:
            continue
        qualified += 1
        # One alert per client for the controlled data snapshot. A new data
        # snapshot can correctly trigger a new review request.
        alert_key = f"urgency-v1:{as_of}:{client_id}:gte-{threshold}"
        if alert_store.was_sent(alert_key):
            already_alerted.append(client_id)
            continue
        notifier.send_urgency_alert(client)
        alert_store.mark_sent(alert_key, client_id, int(score))
        sent.append(client_id)

    return {
        "status": "completed",
        "threshold": threshold,
        "qualified": qualified,
        "sent": sent,
        "already_alerted": already_alerted,
    }
