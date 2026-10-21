from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

from tessera.notifications import (
    UrgencyAlertStore,
    acknowledge_urgency_alert,
    scan_urgency_alerts,
)


class FakeNotifier:
    def __init__(self):
        self.alerts: list[tuple[str, str, int | None]] = []
        self.breaches: list[tuple[str, str]] = []

    def configuration_status(self):
        return "configured"

    def send_urgency_alert(self, client, *, kind, previous_score, potential_impact):
        assert "not a forecast" in potential_impact.lower() or "material review" in potential_impact.lower()
        self.alerts.append((client["client_id"], kind, previous_score))

    def send_breach_alert(self, client, escalation):
        self.breaches.append((client["client_id"], escalation["id"]))


def breach_intelligence(escalation_id: str, review: dict | None = None) -> dict:
    escalation = {"id": escalation_id, "kind": "margin_call", "reason": "Stressed lending value falls 1.0% against a 0.8% cushion",
                  "headline": "Hong Kong property market softens", "severity": "Medium", "date": "2026-10-20"}
    if review:
        escalation["review"] = review
    payload = intelligence(60)
    payload["book"]["priority_queue"][0]["escalation"] = escalation
    return payload


def intelligence(score: int) -> dict:
    return {
        "book": {"priority_queue": [{"client_id": "CL-TEST", "score": score, "next_step": "Review evidence"}]},
        "client_profiles": {
            "CL-TEST": {
                "scenarios": [{"name": "Documented stress", "portfolio_impact_pct": -8.5}]
            }
        },
    }


class NotificationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name)
        patcher = mock.patch.dict("os.environ", {}, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_initial_alert_then_reminder_after_24_hours(self):
        notifier = FakeNotifier()
        patcher = mock.patch("tessera.notifications.TelegramNotifier", return_value=notifier)
        patcher.start()
        self.addCleanup(patcher.stop)
        store = UrgencyAlertStore(self.path / "alerts.json")
        start = datetime(2026, 10, 18, 1, tzinfo=timezone.utc)

        first = scan_urgency_alerts(intelligence(85), store, now=start)
        early = scan_urgency_alerts(intelligence(85), store, now=start + timedelta(hours=23))
        reminder = scan_urgency_alerts(intelligence(85), store, now=start + timedelta(hours=24))

        assert first["initial"] == ["CL-TEST"]
        assert early["reminded"] == []
        assert reminder["reminded"] == ["CL-TEST"]
        assert notifier.alerts == [("CL-TEST", "initial", None), ("CL-TEST", "reminder", 85)]


    def test_breach_alert_is_sent_once_and_never_after_rm_review(self):
        notifier = FakeNotifier()
        patcher = mock.patch("tessera.notifications.TelegramNotifier", return_value=notifier)
        patcher.start()
        self.addCleanup(patcher.stop)
        store = UrgencyAlertStore(self.path / "alerts.json")

        first = scan_urgency_alerts(breach_intelligence("b1"), store)
        repeat = scan_urgency_alerts(breach_intelligence("b1"), store)
        reviewed = scan_urgency_alerts(breach_intelligence("b2", {"status": "dismissed"}), store)
        new_breach = scan_urgency_alerts(breach_intelligence("b3"), store)

        assert first["breach_alerted"] == ["CL-TEST"]
        assert repeat["breach_alerted"] == []
        assert reviewed["breach_alerted"] == []
        assert new_breach["breach_alerted"] == ["CL-TEST"]
        assert notifier.breaches == [("CL-TEST", "b1"), ("CL-TEST", "b3")]
        assert notifier.alerts == []  # a score of 60 stays below the urgency threshold

    def test_unconfigured_telegram_sends_and_records_nothing(self):
        store = UrgencyAlertStore(self.path / "alerts.json")
        result = scan_urgency_alerts(breach_intelligence("b1"), store)
        assert result["status"] == "not_configured"
        assert not (self.path / "alerts.json").exists()

    def test_acknowledgement_pauses_reminder_but_not_material_escalation(self):
        notifier = FakeNotifier()
        patcher = mock.patch("tessera.notifications.TelegramNotifier", return_value=notifier)
        patcher.start()
        self.addCleanup(patcher.stop)
        store = UrgencyAlertStore(self.path / "alerts.json")
        start = datetime(2026, 10, 18, 1, tzinfo=timezone.utc)

        scan_urgency_alerts(intelligence(85), store, now=start)
        acknowledge_urgency_alert(store, "CL-TEST", "Review booked with RM")
        paused = scan_urgency_alerts(intelligence(85), store, now=start + timedelta(hours=25))
        escalated = scan_urgency_alerts(intelligence(90), store, now=start + timedelta(hours=26))

        assert paused["acknowledged"] == ["CL-TEST"]
        assert escalated["escalated"] == ["CL-TEST"]
        assert notifier.alerts == [("CL-TEST", "initial", None), ("CL-TEST", "escalation", 85)]

    def test_concurrent_scans_send_once_across_store_instances(self):
        started, release = threading.Event(), threading.Event()
        notifier = mock.Mock()
        notifier.configuration_status.return_value = "configured"
        def send(*args, **kwargs):
            started.set()
            self.assertTrue(release.wait(3))
        notifier.send_urgency_alert.side_effect = send
        stores = [UrgencyAlertStore(self.path / "alerts.json") for _ in range(2)]
        with mock.patch("tessera.notifications.TelegramNotifier", return_value=notifier), ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(scan_urgency_alerts, intelligence(85), stores[0])
            self.assertTrue(started.wait(3))
            second = pool.submit(scan_urgency_alerts, intelligence(85), stores[1])
            release.set()
            results = [first.result(), second.result()]
        self.assertEqual(notifier.send_urgency_alert.call_count, 1)
        self.assertEqual(sum(len(r["initial"]) for r in results), 1)

    def test_acknowledgement_is_not_overwritten_by_inflight_scan(self):
        started, release = threading.Event(), threading.Event()
        notifier = mock.Mock()
        notifier.configuration_status.return_value = "configured"
        def send(*args, **kwargs):
            started.set()
            self.assertTrue(release.wait(3))
        notifier.send_urgency_alert.side_effect = send
        store = UrgencyAlertStore(self.path / "alerts.json")
        with mock.patch("tessera.notifications.TelegramNotifier", return_value=notifier), ThreadPoolExecutor(max_workers=2) as pool:
            scan = pool.submit(scan_urgency_alerts, intelligence(85), store)
            self.assertTrue(started.wait(3))
            acknowledgement = pool.submit(acknowledge_urgency_alert, store, "CL-TEST", "Reviewed")
            release.set()
            scan.result()
            acknowledgement.result()
        self.assertEqual(store.get("CL-TEST")["status"], "acknowledged")

    def test_corrupt_ledger_fails_without_sending(self):
        path = self.path / "alerts.json"
        path.write_text("broken JSON", encoding="utf-8")
        with mock.patch("tessera.notifications.TelegramNotifier") as notifier:
            notifier.return_value.configuration_status.return_value = "configured"
            with self.assertRaisesRegex(ValueError, "refusing to resend"):
                scan_urgency_alerts(intelligence(85), UrgencyAlertStore(path))
            notifier.return_value.send_urgency_alert.assert_not_called()
