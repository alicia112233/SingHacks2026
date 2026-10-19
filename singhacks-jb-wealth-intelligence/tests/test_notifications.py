from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from tessera.notifications import (
    UrgencyAlertStore,
    acknowledge_urgency_alert,
    scan_urgency_alerts,
)


class FakeNotifier:
    def __init__(self):
        self.alerts: list[tuple[str, str, int | None]] = []

    def send_urgency_alert(self, client, *, kind, previous_score, potential_impact):
        assert "not a forecast" in potential_impact.lower() or "material review" in potential_impact.lower()
        self.alerts.append((client["client_id"], kind, previous_score))


def intelligence(score: int) -> dict:
    return {
        "book": {"priority_queue": [{"client_id": "CL-TEST", "score": score, "next_step": "Review evidence"}]},
        "client_profiles": {
            "CL-TEST": {
                "scenarios": [{"name": "Documented stress", "portfolio_impact_pct": -8.5}]
            }
        },
    }


def test_initial_alert_then_reminder_after_24_hours(tmp_path: Path, monkeypatch):
    notifier = FakeNotifier()
    monkeypatch.setattr("tessera.notifications.TelegramNotifier", lambda: notifier)
    store = UrgencyAlertStore(tmp_path / "alerts.json")
    start = datetime(2026, 10, 18, 1, tzinfo=timezone.utc)

    first = scan_urgency_alerts(intelligence(85), store, now=start)
    early = scan_urgency_alerts(intelligence(85), store, now=start + timedelta(hours=23))
    reminder = scan_urgency_alerts(intelligence(85), store, now=start + timedelta(hours=24))

    assert first["initial"] == ["CL-TEST"]
    assert early["reminded"] == []
    assert reminder["reminded"] == ["CL-TEST"]
    assert notifier.alerts == [("CL-TEST", "initial", None), ("CL-TEST", "reminder", 85)]


def test_acknowledgement_pauses_reminder_but_not_material_escalation(tmp_path: Path, monkeypatch):
    notifier = FakeNotifier()
    monkeypatch.setattr("tessera.notifications.TelegramNotifier", lambda: notifier)
    store = UrgencyAlertStore(tmp_path / "alerts.json")
    start = datetime(2026, 10, 18, 1, tzinfo=timezone.utc)

    scan_urgency_alerts(intelligence(85), store, now=start)
    acknowledge_urgency_alert(store, "CL-TEST", "Review booked with RM")
    paused = scan_urgency_alerts(intelligence(85), store, now=start + timedelta(hours=25))
    escalated = scan_urgency_alerts(intelligence(90), store, now=start + timedelta(hours=26))

    assert paused["acknowledged"] == ["CL-TEST"]
    assert escalated["escalated"] == ["CL-TEST"]
    assert notifier.alerts == [("CL-TEST", "initial", None), ("CL-TEST", "escalation", 85)]
