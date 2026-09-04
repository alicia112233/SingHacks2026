from pathlib import Path
import unittest

import pandas as pd

from tessera.engine import build_intelligence_payload


ROOT = Path(__file__).resolve().parents[1]


class IntelligenceEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = build_intelligence_payload(ROOT / "data")
        cls.holdings = pd.read_csv(ROOT / "data" / "holdings.csv")
        cls.portfolios = pd.read_csv(ROOT / "data" / "portfolios.csv")
        cls.clients = pd.read_csv(ROOT / "data" / "clients.csv")
        cls.events = pd.read_csv(ROOT / "data" / "event_log.csv")
        cls.facilities = pd.read_csv(ROOT / "data" / "credit_facilities.csv")
        cls.cash_needs = pd.read_csv(ROOT / "data" / "planned_cash_needs.csv")
        cls.as_of = cls.holdings.snapshot_date.max()

    def test_book_is_complete_and_time_aware(self):
        self.assertEqual(self.payload["book"]["client_count"], len(self.clients))
        self.assertEqual(self.payload["book"]["portfolio_count"], len(self.portfolios))
        self.assertEqual(self.payload["meta"]["as_of"], self.as_of)
        for profile in self.payload["featured_clients"].values():
            self.assertEqual(len(profile["snapshot_path"]), 5)

    def test_every_client_has_a_complete_review_profile(self):
        profiles = self.payload["client_profiles"]
        self.assertEqual(len(profiles), self.payload["book"]["client_count"])
        for card in self.payload["book"]["priority_queue"]:
            profile = profiles[card["client_id"]]
            self.assertGreaterEqual(len(profile["scenarios"]), 2)
            self.assertGreaterEqual(len(profile["recommendations"]), 2)
            self.assertGreaterEqual(len(profile["evidence_passport"]), 4)

    def test_event_narrative_is_grounded_in_authoritative_log(self):
        signal = self.payload["market_signal"]
        self.assertEqual(signal["date"], self.events.event_date.max())
        self.assertIn("event_log.csv", signal["source"])
        self.assertIn("authoritative", signal["source"])

    def test_hidden_lookthrough_exposures_are_material(self):
        lau = self.payload["featured_clients"]["CL-0014"]
        abdullah = self.payload["featured_clients"]["CL-0019"]
        self.assertGreater(float(lau["headline_metrics"][0]["value"].rstrip("%+")), 40)
        self.assertGreater(float(abdullah["headline_metrics"][0]["value"].rstrip("%+")), 40)

    def test_ltv_uses_margin_trigger_buffer_not_reported_headroom(self):
        ltv = self.payload["featured_clients"]["CL-0014"]["ltv"]
        facility = self.facilities[self.facilities.client_id == "CL-0014"].iloc[0]
        expected_ltv = float(facility[f"ltv_pct_{self.as_of}"])
        trigger = float(facility.margin_call_ltv_pct)
        self.assertAlmostEqual(ltv["ltv_pct"], expected_ltv, places=2)
        self.assertAlmostEqual(ltv["points_to_trigger"], trigger - expected_ltv, places=2)
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

    def test_incomplete_draw_update_is_not_hidden(self):
        cheung = self.payload["featured_clients"]["CL-0012"]
        self.assertEqual(cheung["confidence"]["level"], "Needs verification")
        annual_need = self.cash_needs[
            (self.cash_needs.client_id == "CL-0012")
            & (self.cash_needs.recurrence == "Annual")
        ].iloc[0]
        self.assertIn(f"{annual_need.amount / 1_000_000:.2f}m", cheung["confidence"]["reason"])
        self.assertIn("without a current amount", cheung["confidence"]["reason"])

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
