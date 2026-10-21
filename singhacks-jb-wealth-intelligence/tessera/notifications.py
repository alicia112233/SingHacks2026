"""Human-controlled Telegram alerts for high-urgency TESSERA reviews."""

from __future__ import annotations

import html
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib import error, request

from tessera.alert_store import UrgencyAlertStore, PostgresUrgencyAlertStore, production_urgency_alert_store
from tessera.recommendation_validation import finite


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
        self._send(message)

    def send_breach_alert(self, client: dict[str, Any], escalation: dict[str, Any]) -> None:
        """Tell the RM that news may have breached a portfolio line; the RM confirms or dismisses it."""

        client_id = str(client.get("client_id", "")).strip()
        if not client_id or not escalation.get("reason"):
            raise TelegramNotificationError("Breach alert is missing a client reference or reason.")
        message = (
            "<b>TESSERA • breach alert</b>\n\n"
            f"Client reference: <code>{html.escape(client_id)}</code>\n"
            f"What crossed the line: {html.escape(str(escalation['reason']))}.\n"
            f"Headline ({html.escape(str(escalation.get('severity', '')))}, {html.escape(str(escalation.get('date', '')))}): "
            f"{html.escape(str(escalation.get('headline', '')))}\n"
            "Next step: open the client in TESSERA and confirm or dismiss the alert.\n\n"
            "This is an illustrative stress test, not a forecast, and it does not approve a trade or client action."
        )
        self._send(message)

    def _send(self, message: str) -> None:
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
        if not token or not chat_id:
            raise TelegramNotificationError(
                "Telegram is not configured. Add TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to .env.local."
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


def acknowledge_urgency_alert(
    alert_store: Any, client_id: str, note: str = ""
) -> dict[str, Any]:
    """Pause reminders while preserving the state needed for escalation alerts."""

    def acknowledge(existing):
        if existing is None:
            raise ValueError("No urgency alert exists for this client yet.")
        timestamp = _now().isoformat()
        updated = {**existing, "status": "acknowledged", "acknowledged_at": timestamp,
                   "acknowledgement_note": note[:500], "last_checked_at": timestamp}
        return updated, updated
    return alert_store.transact(client_id, acknowledge)


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


def _scan_client(client, intelligence, existing, policy, current_time, notifier):
    """Called under the store transaction so two scans cannot deliver the same alert."""
    client_id, score = client["client_id"], int(client["score"])
    timestamp = current_time.isoformat()
    state = dict(existing or {})
    if score < policy["threshold"]:
        if existing:
            state.update(status="below_threshold", last_score=score, last_checked_at=timestamp)
        return state if existing else None, "below_threshold"

    prior_score = state.get("last_alert_score")
    last_alert_at = _as_utc(state.get("last_alert_at"))
    status = state.get("status", "open")
    kind = None
    if not existing or status == "below_threshold":
        kind = "initial"
    elif isinstance(prior_score, (int, float)) and (
        score >= policy["escalation_score"] > prior_score or score >= prior_score + policy["escalation_delta"]
    ):
        kind = "escalation"
    elif status == "open" and (last_alert_at is None or current_time - last_alert_at >= timedelta(hours=policy["reminder_hours"])):
        kind = "reminder"

    if kind:
        notifier.send_urgency_alert(client, kind=kind, previous_score=prior_score,
                                   potential_impact=potential_impact_to_review(client, intelligence))
        if kind == "initial":
            state = _fresh_state(client_id, score, timestamp)
        else:
            state.update(status="open" if kind == "escalation" else status,
                         last_alert_at=timestamp, last_checked_at=timestamp,
                         last_score=score, last_alert_score=score, last_alert_kind=kind)
        return state, {"initial": "initial", "reminder": "reminded", "escalation": "escalated"}[kind]
    state.update(last_score=score, last_checked_at=timestamp)
    return state, "acknowledged" if status == "acknowledged" else None


def scan_urgency_alerts(intelligence, alert_store, *, now=None):
    """Serialize alert lifecycle updates with scans and acknowledgements."""
    policy = notification_policy()
    queue = intelligence.get("book", {}).get("priority_queue", [])
    if not isinstance(queue, list):
        raise ValueError("Priority queue is unavailable.")
    current_time = now or _now()
    notifier = TelegramNotifier()
    if notifier.configuration_status() != "configured":
        # Nothing can be delivered, so record nothing; alerts start once Telegram is set up.
        return {"status": "not_configured", "policy": policy}
    result = {"status": "completed", "policy": policy, "qualified": 0,
              "initial": [], "reminded": [], "escalated": [], "acknowledged": [], "below_threshold": []}
    result["breach_alerted"] = []
    for client in queue:
        if not isinstance(client, dict) or not client.get("client_id") or not finite(client.get("score")):
            continue
        client_id = str(client["client_id"])
        result["qualified"] += int(client["score"] >= policy["threshold"])
        category = alert_store.transact(client_id, lambda existing: _scan_client(client, intelligence, existing, policy, current_time, notifier))
        if category:
            result[category].append(client_id)
        escalation = client.get("escalation")
        # One message per breach, and none once the RM has confirmed or dismissed it.
        if isinstance(escalation, dict) and escalation.get("id") and not escalation.get("review"):
            if alert_store.transact(f"breach:{client_id}", lambda existing: _scan_breach(client, escalation, existing, current_time, notifier)):
                result["breach_alerted"].append(client_id)
    return result


def _scan_breach(client, escalation, existing, current_time, notifier):
    """Called under the store transaction so two scans cannot send the same breach twice."""
    if existing and existing.get("escalation_id") == escalation["id"]:
        return existing, False
    notifier.send_breach_alert(client, escalation)
    return {"client_id": client["client_id"], "escalation_id": escalation["id"], "kind": escalation.get("kind"),
            "headline": escalation.get("headline"), "sent_at": current_time.isoformat()}, True
