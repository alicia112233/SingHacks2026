import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import app as app_module
from app import DecisionStore, TesseraHandler


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


if __name__ == "__main__":
    unittest.main()
