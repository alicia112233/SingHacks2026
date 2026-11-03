"""Cloud news must survive cold starts and invalidate independently cached analytics."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tessera.cloud_outputs import LIVE_EVENTS_KEY, json_bytes, merge_events, mirror_events
from tessera.services import IntelligenceService
from tessera.market_news import refresh


class MemoryOutputs:
    def __init__(self):
        self.values = {}

    def read_json(self, key, default=None):
        return self.values.get(key, default)

    def put_json(self, key, value):
        self.values[key] = value


class CloudOutputTests(unittest.TestCase):
    def test_merging_stale_register_preserves_other_worker_and_capture_time(self):
        first = {"event_id": "a", "retrieved_at": "2026-01-01", "event_date": "2026-01-01"}
        other = {"event_id": "b", "event_date": "2026-01-02"}
        stale = {**first, "retrieved_at": "2026-02-01", "publisher": "Reuters"}
        result = merge_events([first, other], [stale])
        self.assertEqual([event["event_id"] for event in result], ["a", "b"])
        self.assertEqual(result[0]["retrieved_at"], "2026-01-01")
        self.assertEqual(result[0]["publisher"], "Reuters")

    def test_cold_worker_loads_shared_events_and_not_stale_local_mirror(self):
        store = MemoryOutputs()
        store.put_json(LIVE_EVENTS_KEY, [{"event_id": "cloud"}])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mirror = root / "live.json"
            mirror.write_text('[{"event_id":"stale"}]')
            service = IntelligenceService(root, mirror, output_store=store)
            with mock.patch("tessera.services.build_intelligence_payload", return_value={"book": "cloud"}) as build:
                self.assertEqual(service.get(), {"book": "cloud"})
                service.get()
                self.assertEqual(build.call_count, 1)
                store.put_json(LIVE_EVENTS_KEY, [{"event_id": "new-cloud-event"}])
                service.get()
                self.assertEqual(build.call_count, 2)
            self.assertEqual(json.loads(mirror.read_text()), [{"event_id": "new-cloud-event"}])
            self.assertEqual(store.read_json("intelligence/current.json"), {"book": "cloud"})

    def test_cloud_failure_does_not_silently_use_empty_local_news(self):
        store = MemoryOutputs()
        store.read_json = mock.Mock(side_effect=RuntimeError("offline"))
        with tempfile.TemporaryDirectory() as directory:
            service = IntelligenceService(Path(directory), output_store=store)
            with self.assertRaisesRegex(RuntimeError, "offline"):
                service.get()

    def test_frozen_news_reads_cloud_on_a_fresh_instance(self):
        store = MemoryOutputs()
        store.put_json(LIVE_EVENTS_KEY, [{"event_id": "persisted"}])
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(
            "os.environ", {"TESSERA_NEWS_FROZEN": "true", "TESSERA_LIVE_NEWS_ENABLED": "true"}
        ):
            result = refresh(Path(directory), Path(directory) / "fresh.json", output_store=store)
        self.assertEqual(result["status"], "frozen")
        self.assertEqual(result["events"], [{"event_id": "persisted"}])

    def test_unchanged_mirror_does_not_invalidate_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.json"
            mirror_events(path, [])
            before = path.stat().st_mtime_ns
            mirror_events(path, [])
            self.assertEqual(path.stat().st_mtime_ns, before)
        with self.assertRaises(ValueError):
            json_bytes({"bad": float("nan")})

    def test_hosted_chat_persists_answer_before_returning_it(self):
        import api.index as api
        store = MemoryOutputs()
        answer = {"answer": "Grounded response", "sources": []}
        with mock.patch.object(api, "OUTPUTS", store), mock.patch.object(api.INTELLIGENCE, "get", return_value={}), mock.patch.object(api, "answer_chat", return_value=answer):
            response = api.app.test_client().post("/api/chat", json={"client_id": "CL-0012", "question": "Current AUM?"})
        self.assertEqual(response.status_code, 200)
        keys = [key for key in store.values if key.startswith("chat/")]
        self.assertEqual(len(keys), 1)
        self.assertEqual(store.values[keys[0]], response.json)

    def test_hosted_health_reports_database_failure(self):
        import api.index as api
        store = mock.Mock()
        store.inventory.side_effect = RuntimeError("Database unavailable")
        with mock.patch.object(api, "OUTPUTS", store):
            response = api.app.test_client().get("/health")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json["backend_output_storage"], "unavailable")
        self.assertEqual(response.json["status"], "degraded")

    def test_local_server_can_use_the_same_cloud_stores(self):
        import app
        original = {key: getattr(app, key) for key in ("OUTPUTS", "INTELLIGENCE", "DECISIONS", "URGENCY_ALERTS")}
        try:
            with mock.patch.dict("os.environ", {"TESSERA_STORAGE_BACKEND": "postgresql"}), mock.patch.object(app, "production_output_store", return_value="outputs"), mock.patch.object(app, "production_decision_store", return_value="decisions"), mock.patch.object(app, "production_urgency_alert_store", return_value="alerts"):
                app.configure_storage()
            self.assertEqual(app.INTELLIGENCE.output_store, "outputs")
            self.assertEqual(app.DECISIONS, "decisions")
            self.assertEqual(app.URGENCY_ALERTS, "alerts")
        finally:
            for key, value in original.items():
                setattr(app, key, value)
