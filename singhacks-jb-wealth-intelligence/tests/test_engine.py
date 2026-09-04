from pathlib import Path
import unittest

from tessera.engine import DATASET_TODAY, build_intelligence_payload


ROOT = Path(__file__).resolve().parents[1]


class IntelligenceEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = build_intelligence_payload(ROOT / "data")

    def test_book_is_complete_and_time_aware(self):
        self.assertEqual(self.payload["book"]["client_count"], 20)
        self.assertEqual(self.payload["book"]["portfolio_count"], 24)
        self.assertEqual(self.payload["meta"]["as_of"], DATASET_TODAY)
        for profile in self.payload["featured_clients"].values():
            self.assertEqual(len(profile["snapshot_path"]), 5)

    def test_event_narrative_is_grounded_in_authoritative_log(self):
        signal = self.payload["market_signal"]
        self.assertEqual(signal["date"], "2026-08-05")
        self.assertIn("event_log.csv", signal["source"])
        self.assertIn("authoritative", signal["source"])

    def test_hidden_lookthrough_exposures_are_material(self):
        lau = self.payload["featured_clients"]["CL-0014"]
        abdullah = self.payload["featured_clients"]["CL-0019"]
        self.assertEqual(lau["headline_metrics"][0]["value"], "49.0%+")
        self.assertEqual(abdullah["headline_metrics"][0]["value"], "42.1%+")

    def test_ltv_uses_margin_trigger_buffer_not_reported_headroom(self):
        ltv = self.payload["featured_clients"]["CL-0014"]["ltv"]
        self.assertAlmostEqual(ltv["ltv_pct"], 69.41, places=2)
        self.assertAlmostEqual(ltv["points_to_trigger"], 0.59, places=2)
        self.assertLess(ltv["lending_value_buffer_m"], ltv["reported_headroom_m"])

    def test_scenarios_are_symmetric_questions_not_forecasts(self):
        cheung = self.payload["featured_clients"]["CL-0012"]
        abdullah = self.payload["featured_clients"]["CL-0019"]
        self.assertLess(cheung["scenarios"][0]["portfolio_impact_pct"], 0)
        self.assertGreater(cheung["scenarios"][1]["portfolio_impact_pct"], 0)
        self.assertLess(abdullah["scenarios"][0]["portfolio_impact_pct"], 0)
        self.assertGreater(abdullah["scenarios"][1]["portfolio_impact_pct"], 0)
        for profile in (cheung, abdullah):
            for scenario in profile["scenarios"]:
                self.assertTrue(
                    "not a forecast" in scenario["description"].lower()
                    or "no probability" in scenario["description"].lower()
                )

    def test_conflicting_draw_amount_is_not_hidden(self):
        cheung = self.payload["featured_clients"]["CL-0012"]
        self.assertEqual(cheung["confidence"]["level"], "Needs verification")
        self.assertIn("1.10m", cheung["confidence"]["reason"])
        self.assertIn("1.28m", cheung["confidence"]["reason"])

    def test_every_recommendation_keeps_the_rm_in_control(self):
        for profile in self.payload["featured_clients"].values():
            for recommendation in profile["recommendations"]:
                self.assertTrue(recommendation["reversible"])
                self.assertTrue(recommendation["suitability"])
            self.assertGreaterEqual(len(profile["evidence_passport"]), 4)

    def test_capacity_band_contains_five_now_conversations(self):
        queue = self.payload["book"]["priority_queue"]
        self.assertEqual(sum(row["priority"] == "Now" for row in queue), 5)
        self.assertEqual(queue, sorted(queue, key=lambda row: row["score"], reverse=True))


if __name__ == "__main__":
    unittest.main()
