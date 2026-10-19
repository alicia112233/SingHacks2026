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
            with self.assertRaisesRegex(ValueError, "refusing to resend"):
                scan_urgency_alerts(intelligence(85), UrgencyAlertStore(path))
            notifier.return_value.send_urgency_alert.assert_not_called()
