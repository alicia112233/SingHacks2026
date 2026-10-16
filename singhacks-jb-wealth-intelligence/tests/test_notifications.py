from __future__ import annotations

from pathlib import Path

from tessera.notifications import UrgencyAlertStore, scan_urgency_alerts


class FakeNotifier:
    def __init__(self):
        self.client_ids: list[str] = []

    def send_urgency_alert(self, client):
        self.client_ids.append(client["client_id"])


def test_scan_sends_once_for_scores_at_or_above_threshold(tmp_path: Path, monkeypatch):
    notifier = FakeNotifier()
    monkeypatch.setattr("tessera.notifications.TelegramNotifier", lambda: notifier)
    intelligence = {
        "meta": {"as_of": "2026-10-16"},
        "book": {"priority_queue": [
            {"client_id": "CL-LOW", "score": 79},
            {"client_id": "CL-AT", "score": 80, "next_step": "Review evidence"},
            {"client_id": "CL-HIGH", "score": 91, "next_step": "Review evidence"},
        ]},
    }
    store = UrgencyAlertStore(tmp_path / "alerts.json")

    first = scan_urgency_alerts(intelligence, store)
    second = scan_urgency_alerts(intelligence, store)

    assert first["sent"] == ["CL-AT", "CL-HIGH"]
    assert second["sent"] == []
    assert second["already_alerted"] == ["CL-AT", "CL-HIGH"]
    assert notifier.client_ids == ["CL-AT", "CL-HIGH"]
