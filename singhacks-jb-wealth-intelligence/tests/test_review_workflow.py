"""Regression cases for action identity, persistence and approval boundaries."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import api.index as api
from tessera.engine import build_intelligence_payload
from tessera.evaluation import _evaluation_packet, evaluate_recommendation
from tessera.recommendation_validation import revalidate_text, validate_numbers
from tessera.services import DecisionStore, reviewed_intelligence

ROOT = Path(__file__).resolve().parents[1]


class ReviewWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = build_intelligence_payload(ROOT / "data")

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "decisions.json"
        self.store = DecisionStore(self.path)
        self.data = deepcopy(self.payload)
        for patcher in (mock.patch.object(api, "decision_store", return_value=self.store),
                        mock.patch.object(api.INTELLIGENCE, "get", side_effect=lambda: self.data),
                        mock.patch("tessera.evaluation.retrieve_recommendation_evidence", return_value={"evidence": [], "status": "disabled", "reason": "test"}),
                        mock.patch.dict("os.environ", {"TESSERA_EXTERNAL_JUDGES_ENABLED": "false"})):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = api.app.test_client()

    def action(self, index=1):
        return self.client.get("/api/intelligence").json["client_profiles"]["CL-0011"]["recommendations"][index]

    def request_body(self, index=1):
        action = self.action(index)
        return {"client_id": "CL-0011", "recommendation_index": index, "recommendation_id": action["id"], "version": action["version"]}

    def approve(self, index=1, body=None):
        return self.client.post("/api/decisions", json={**(body or self.request_body(index)), "action": "approved", "note": "Checked the source evidence and suitability"})

    def panel(self, score=30, verdict="block", index=1):
        def judge(model, packet, token):
            return {"model": model, "provider": "test", "status": "Completed", "score": score, "verdict": verdict}
        with mock.patch("tessera.evaluation._external_judges_enabled", return_value=True), mock.patch("tessera.evaluation._gateway_token", return_value="test"), mock.patch("tessera.evaluation._call_judge", side_effect=judge):
            response = self.client.post("/api/evaluations", json=self.request_body(index))
        self.assertEqual(response.status_code, 200, response.json)
        return response.json

    def test_semantic_edits_cannot_inherit_a_score(self):
        original = self.action()
        for text in ("Buy an unapproved product immediately; suitability checks are unnecessary.", original["detail"].replace("45", "75").replace("75%", "45%")):
            response = self.client.post("/api/decisions", json={**self.request_body(), "action": "edited", "note": text})
            self.assertEqual(response.status_code, 201)
            self.assertEqual(self.action()["risk_validation"]["score"], 0)
            self.assertEqual(self.approve().status_code, 400)
        restored = self.client.post("/api/decisions", json={**self.request_body(), "action": "edited", "note": original["detail"]})
        self.assertEqual(restored.status_code, 201)
        self.assertEqual(self.approve().status_code, 201)

    def test_range_bounds_require_one_source_and_correct_roles(self):
        evidence = [{"value": 45, "unit": "percent", "source": "A", "field": "min_pct"}, {"value": 75, "unit": "percent", "source": "B", "field": "max_pct"}]
        self.assertTrue(validate_numbers("45-75%", evidence)[1])
        evidence[1]["source"] = "A"
        self.assertFalse(validate_numbers("45-75%", evidence)[1])
        self.assertTrue(validate_numbers("75-45%", evidence)[1])

    def test_panel_block_survives_reload_retry_and_blocks_direct_api(self):
        stale_body = self.request_body()
        self.assertEqual(self.panel()["consensus"]["score"], 30)
        with mock.patch.object(api, "decision_store", return_value=DecisionStore(self.path)):
            self.assertEqual(self.action()["risk_validation"]["score"], 30)
            self.assertEqual(self.approve(body=stale_body).status_code, 400)
            skipped = self.client.post("/api/evaluations", json=self.request_body())
            self.assertEqual(skipped.json["consensus"]["score"], 30)
            self.assertEqual(self.approve().status_code, 400)
        # A changed evidence version requires a completed new assessment.
        self.data["client_profiles"]["CL-0011"]["recommendations"][1]["evidence_version"] = "new evidence"
        self.assertEqual(self.approve().status_code, 400)
        self.panel(80, "support_for_rm_review")
        self.assertEqual(self.approve().status_code, 201)

    def test_alternative_is_durable_and_does_not_mutate_cached_payload(self):
        count = len(self.data["client_profiles"]["CL-0011"]["recommendations"])
        body = self.request_body()
        response = self.client.post("/api/recommendations/alternate", json={**body, "dismissed_index": 1})
        self.assertEqual(response.status_code, 200, response.json)
        selected = response.json["recommendation"]
        self.assertEqual(len(self.data["client_profiles"]["CL-0011"]["recommendations"]), count)
        self.data = deepcopy(self.payload)
        with mock.patch.object(api, "decision_store", return_value=DecisionStore(self.path)):
            self.assertEqual(self.action(count)["id"], selected["id"])
            self.assertEqual(self.approve(count).status_code, 201)
        other = deepcopy(self.payload)
        other["client_profiles"]["CL-0011"]["alternative_candidates"][0]["detail"] = "Other dataset"
        self.assertNotEqual(self.action(count)["detail"], "Other dataset")

    def test_stale_version_wrong_identity_and_missing_identity_are_rejected(self):
        body = self.request_body()
        for override in ({"version": "stale"}, {"recommendation_id": "other"}, {"recommendation_id": None}):
            self.assertEqual(self.approve(body={**body, **override}).status_code, 400)
        self.assertEqual(self.approve().status_code, 201)
        self.data["client_profiles"]["CL-0011"]["recommendations"][1]["evidence_version"] = "changed"
        self.assertNotIn("CL-0011:1", self.client.get("/api/decisions").json["effective"])

    def test_external_packet_has_no_narratives_or_identifiers(self):
        client = deepcopy(self.data["client_profiles"]["CL-0011"])
        secret = "PRIVATE_RM_NOTE ClientName CL-0011 account-123"
        for field in ("objectives", "risk_profile", "evidence_passport", "tension", "rm_notes"):
            client[field] = {"nested": secret}
        client["cash_needs"].append({"amount_usd_m": secret, "note": secret})
        action = {**client["recommendations"][1], "detail": secret, "title": secret, "suitability": secret}
        encoded = json.dumps(_evaluation_packet(client, action, [{"excerpt": secret, "metadata": {"client_id": secret}}]))
        self.assertNotIn("PRIVATE_RM_NOTE", encoded)
        self.assertNotIn("CL-0011", encoded)
        self.assertNotIn("ClientName", encoded)
        self.assertIn("mandate", encoded)

    def test_concurrent_alternatives_are_distinct_and_durable(self):
        from concurrent.futures import ThreadPoolExecutor
        from tessera.services import record_alternative
        body = {**self.request_body(), "dismissed_index": 1}
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(record_alternative, body, self.data, self.store) for _ in range(2)]
            selected = [future.result()["recommendation"]["id"] for future in futures]
        self.assertEqual(len(set(selected)), 2)
        restored = reviewed_intelligence(self.data, DecisionStore(self.path).snapshot())
        ids = {a["id"] for a in restored["client_profiles"]["CL-0011"]["recommendations"]}
        self.assertTrue(set(selected).issubset(ids))

    def test_production_mode_is_rejected(self):
        from tessera.services import IntelligenceService
        with mock.patch.dict("os.environ", {"TESSERA_MODE": "production"}):
            with self.assertRaisesRegex(RuntimeError, "demo mode only"):
                IntelligenceService(ROOT / "data").get()

    def test_low_score_is_blocked_without_explicit_hard_stop(self):
        payload = deepcopy(self.data)
        payload["client_profiles"]["CL-0011"]["recommendations"][1]["risk_validation"]["score"] = 30
        self.assertEqual(evaluate_recommendation(payload, "CL-0011", 1)["deterministic"]["status"], "Blocked")

    def test_browser_urgency_does_not_drop_after_approval(self):
        script = r"""
const fs=require('fs'), vm=require('vm'), assert=require('assert');
const context=vm.createContext({console});
vm.runInContext(fs.readFileSync('web/app.js','utf8').replace(/init\(\);\s*$/, ''),context);
vm.runInContext(`state.decisions={effective:{x:{client_id:'CL-0011',action:'approved',recommendation_index:0}}}`,context);
assert.equal(vm.runInContext("urgencyScore({client_id:'CL-0011',score:90})",context),90);
"""
        result = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
