import json
import tempfile
import threading
import unittest
from unittest import mock
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import app as app_module
from app import DecisionStore, TesseraHandler
from api.index import app as vercel_app
from tessera.services import create_decision_record


class DecisionStoreTests(unittest.TestCase):
    def test_ledger_is_durable_and_latest_decision_is_effective(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "decisions.json"
            store = DecisionStore(path)
            approved = {
                "recommendation_id": "CL-0012:0",
                "action": "approved",
            }
            dismissed = {
                "recommendation_id": "CL-0012:0",
                "action": "dismissed",
            }
            store.append(approved)
            store.append(dismissed)

            snapshot = DecisionStore(path).snapshot()
            self.assertEqual(len(snapshot["records"]), 2)
        self.assertEqual(snapshot["effective"]["CL-0012:0"]["action"], "dismissed")

    def test_decision_request_is_validated_against_current_recommendations(self):
        intelligence = app_module.INTELLIGENCE.get()
        record = create_decision_record(
            {
                "client_id": "CL-0012",
                "recommendation_index": 0,
                "action": "dismissed",
                "note": "Not suitable after review",
            },
            intelligence,
        )
        self.assertEqual(record["recommendation_id"], "CL-0012:0")
        self.assertEqual(record["action"], "dismissed")
        self.assertEqual(record["client_name"], intelligence["featured_clients"]["CL-0012"]["name"])

        with self.assertRaisesRegex(ValueError, "Unknown client"):
            create_decision_record(
                {"client_id": "NOT-A-CLIENT", "recommendation_index": 0, "action": "approved"},
                intelligence,
            )


class ApplicationRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.original_decisions = app_module.DECISIONS
        app_module.DECISIONS = DecisionStore(Path(cls.directory.name) / "decisions.json")
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), TesseraHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)
        app_module.DECISIONS = cls.original_decisions
        cls.directory.cleanup()

    def test_root_and_application_routes_return_the_shell(self):
        for path in ["/", "/scenario-studio?client=CL-0019", "/clients/CL-0012", "/evidence-ledger"]:
            with self.subTest(path=path), urlopen(f"{self.base_url}{path}") as response:
                self.assertEqual(response.status, 200)
                self.assertIn("TESSERA", response.read().decode("utf-8"))

    def test_health_and_favicon_do_not_return_404(self):
        with urlopen(f"{self.base_url}/health") as response:
            self.assertEqual(json.load(response)["status"], "ok")
        with urlopen(f"{self.base_url}/favicon.ico") as response:
            self.assertEqual(response.status, 204)

    def test_missing_static_asset_still_returns_404(self):
        with self.assertRaises(HTTPError) as error:
            urlopen(f"{self.base_url}/missing.css")
        self.assertEqual(error.exception.code, 404)

    def test_dismiss_and_restore_are_persisted_by_the_api(self):
        for action in ["dismissed", "pending"]:
            body = json.dumps(
                {
                    "client_id": "CL-0012",
                    "recommendation_index": 0,
                    "action": action,
                    "note": "Reviewed by automated test",
                }
            ).encode("utf-8")
            request = Request(
                f"{self.base_url}/api/decisions",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(request) as response:
                self.assertEqual(response.status, 201)

        with urlopen(f"{self.base_url}/api/decisions") as response:
            snapshot = json.load(response)
        self.assertEqual(snapshot["effective"]["CL-0012:0"]["action"], "pending")
        self.assertEqual(len(snapshot["records"]), 2)


class VercelRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = vercel_app.test_client()

    def test_intelligence_and_health_routes(self):
        intelligence = self.client.get("/api/intelligence")
        self.assertEqual(intelligence.status_code, 200)
        self.assertIn("meta", intelligence.get_json())

        health = self.client.get("/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.get_json()["status"], "ok")

    def test_frontend_and_direct_application_routes(self):
        for path in ["/", "/clients/CL-0012", "/scenario-studio", "/evidence-ledger"]:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn(b"TESSERA", response.data)
        self.assertEqual(self.client.get("/app.js").status_code, 200)
        self.assertEqual(self.client.get("/styles.css").status_code, 200)

    def test_unconfigured_hosted_ledger_fails_clearly(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            response = self.client.get("/api/decisions")
        self.assertEqual(response.status_code, 503)
        self.assertIn("DATABASE_URL", response.get_json()["error"])


if __name__ == "__main__":
    unittest.main()