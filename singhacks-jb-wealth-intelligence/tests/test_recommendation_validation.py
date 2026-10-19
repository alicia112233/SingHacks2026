from copy import deepcopy
from pathlib import Path
import json
import subprocess
import tempfile
import unittest
from unittest import mock

from tessera.engine import build_intelligence_payload, load_dataset, _recommendation_risk_validation, _alternative_recommendation_candidates
from tessera.services import DecisionStore
from tessera.recommendation_validation import revalidate_text

ROOT = Path(__file__).resolve().parents[1]


class ActionValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = load_dataset(ROOT / "data")
        cls.payload = build_intelligence_payload(ROOT / "data")

    def test_pictured_actions_have_independent_scores_and_valid_mandate(self):
        actions = self.payload["client_profiles"]["CL-0011"]["recommendations"]
        self.assertEqual([a["risk_validation"]["score"] for a in actions], [76, 84, 64, 76])
        mandate = actions[1]["risk_validation"]
        self.assertFalse(mandate["blockers"])
        self.assertTrue(any(c["value"] == 75 and c["sources"][0]["field"] == "max_pct" for c in mandate["resolved_claims"]))
        for c in self.payload["client_profiles"].values():
            for a in c["recommendations"] + _alternative_recommendation_candidates(self.bundle, c):
                self.assertIn("assessment_kind", a)
                result = _recommendation_risk_validation(self.bundle, c, a)
                self.assertFalse(result["blockers"], (c["client_id"], a["title"], result["blockers"]))
                self.assertEqual(result["raw_score"], sum(d["score"] for d in result["dimensions"]))

    def test_numeric_ranges_units_and_unrelated_values(self):
        action = self.payload["client_profiles"]["CL-0011"]["recommendations"][1]
        original = action["risk_validation"]
        for dash in ("\u2013", "-"):
            self.assertFalse(revalidate_text(original, action["detail"].replace("\u2013", dash))["blockers"])
        for text in ("Review fixed income outside 45-76% band.", "Review USD 75m exposure.", "Review 987654% exposure."):
            self.assertEqual(revalidate_text(original, text)["score"], 0, text)

    def test_missing_relevant_evidence_lowers_only_affected_action(self):
        profile = deepcopy(self.payload["client_profiles"]["CL-0011"])
        funding, mandate, movement = profile["recommendations"][:3]
        profile["cash_needs"] = []
        changed = _recommendation_risk_validation(self.bundle, profile, {**funding, "detail": "Confirm the funding requirement."})
        self.assertLess(changed["raw_score"], funding["risk_validation"]["raw_score"])
        for a in (mandate, movement):
            result = _recommendation_risk_validation(self.bundle, profile, a)
            self.assertEqual(result["score"], a["risk_validation"]["score"])
            self.assertFalse(any(cap["value"] == 79 for cap in result["caps"]))
        renamed = _recommendation_risk_validation(self.bundle, profile, {**mandate, "title": "New wording"})
        self.assertEqual(renamed["score"], mandate["risk_validation"]["score"])

    def test_hard_stops_survive_and_unknown_actions_fail_closed(self):
        profile = self.payload["client_profiles"]["CL-0011"]
        action = profile["recommendations"][1]
        for overrides in ({"suitability": ""}, {"reversible": False}):
            result = _recommendation_risk_validation(self.bundle, profile, {**action, **overrides})
            self.assertEqual(result["score"], 0)
        result = _recommendation_risk_validation(self.bundle, profile, {**action, "assessment_kind": "unknown", "detail": "Review."})
        self.assertEqual(result["band"], "Blocked")

    def test_api_revalidates_edits_and_blocks_approval(self):
        import api.index as api
        with tempfile.TemporaryDirectory() as directory:
            store = DecisionStore(Path(directory) / "decisions.json")
            with mock.patch.object(api, "decision_store", return_value=store), mock.patch.object(api.INTELLIGENCE, "get", return_value=self.payload):
                client = api.app.test_client()
                action = self.payload["client_profiles"]["CL-0011"]["recommendations"][1]
                body = {"client_id": "CL-0011", "recommendation_index": 1, "recommendation_id": action["id"], "version": action["version"]}
                edited = client.post("/api/decisions", json={**body, "action": "edited", "note": "Review fixed income outside 45-76% band."})
                self.assertEqual(edited.status_code, 201)
                self.assertEqual(edited.json["reviews"]["CL-0011:1"]["risk_validation"]["score"], 0)
                body["version"] = edited.json["reviews"]["CL-0011:1"]["version"]
                with mock.patch.dict("os.environ", {"TESSERA_EXTERNAL_JUDGES_ENABLED": "false"}):
                    panel = client.post("/api/evaluations", json=body)
                self.assertEqual(panel.status_code, 200)
                self.assertEqual(panel.json["deterministic"]["score"], 0)
                approval = {**body, "action": "approved", "note": "Reviewed suitability and evidence with the client"}
                self.assertEqual(client.post("/api/decisions", json=approval).status_code, 400)
                # Reload from durable notes; an edit cannot bypass the original control.
                self.assertEqual(client.get("/api/decisions").json["reviews"]["CL-0011:1"]["risk_validation"]["score"], 0)
                corrected = client.post("/api/decisions", json={**body, "action": "edited", "note": action["detail"]})
                self.assertGreater(corrected.json["reviews"]["CL-0011:1"]["risk_validation"]["score"], 0)
                approval["version"] = corrected.json["reviews"]["CL-0011:1"]["version"]
                self.assertEqual(client.post("/api/decisions", json=approval).status_code, 201)

    def test_rendered_html_separates_blocked_actions_and_keeps_indices(self):
        script = r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const code = fs.readFileSync('web/app.js', 'utf8').replace(/init\(\);\s*$/, '');
const context = vm.createContext({console});
vm.runInContext(code, context);
const client = JSON.parse(fs.readFileSync(0, 'utf8'));
context.client = client;
vm.runInContext('state.data = {client_profiles: {[client.client_id]: client}}', context);
vm.runInContext(`state.decisions = {records: [], effective: {}, reviews: {'CL-0011:1': {...client.recommendations[1], detail: 'Bad quantity', risk_validation: {...client.recommendations[1].risk_validation, score: 0, band: 'Blocked', blockers: ['Unsupported numeric claim: 76 percent']}}}}`, context);
const html = vm.runInContext('recommendationsHTML(client)', context);
assert(html.includes('Needs correction'));
assert(html.indexOf('data-recommendation="1"') > html.indexOf('Needs correction'));
assert(html.indexOf('data-recommendation="2"') < html.indexOf('Needs correction'));
assert(html.includes('Unsupported numeric claim: 76 percent'));
const draft = html.slice(html.indexOf('data-recommendation="1"'));
assert(!draft.includes('data-decision="approved"'));
assert(draft.includes('data-index="1"'));
console.log('Rendered action sections and disabled approval verified');
"""
        result = subprocess.run(["node", "-e", script], cwd=ROOT, input=json.dumps(self.payload["client_profiles"]["CL-0011"]), text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
