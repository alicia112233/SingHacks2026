from pathlib import Path
from types import SimpleNamespace
import re
import unittest

import pandas as pd

from tessera.contradictions import detect
from tessera.engine import _detection, build_intelligence_payload, load_dataset

ROOT = Path(__file__).resolve().parents[1]


class ContradictionDetectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = load_dataset(ROOT / "data")
        cls.payload = build_intelligence_payload(ROOT / "data")
        cls.queue = {card["client_id"]: card for card in cls.payload["book"]["priority_queue"]}

    def test_rules_name_no_client(self):
        source = (ROOT / "tessera" / "contradictions.py").read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"CL-\d{4}", source))
        self.assertNotIn("CLIENT_RULES", (ROOT / "tessera" / "engine.py").read_text(encoding="utf-8"))

    def test_featured_lookthrough_themes_are_detected(self):
        abdullah = _detection(self.bundle, "CL-0019")
        self.assertEqual(abdullah["theme"], "shipping and energy")
        self.assertEqual(abdullah["theme_ids"], ["SYN-EQ-0008", "SYN-EQ-0025", "SYN-SP-0505", "SYN-ST-0104"])
        self.assertAlmostEqual(abdullah["theme_exposure_pct"], 42.1)
        self.assertEqual(abdullah["primary"]["kind"], "wealth_concentration")
        self.assertIn("rm_notes.json: N-025", abdullah["primary"]["sources"])

        lau = _detection(self.bundle, "CL-0014")
        self.assertEqual(lau["theme"], "property")
        self.assertAlmostEqual(lau["theme_exposure_pct"], 49.0)

        hartono = _detection(self.bundle, "CL-0001")
        self.assertEqual(hartono["theme"], "energy")
        self.assertAlmostEqual(hartono["theme_exposure_pct"], 45.0)

    def test_a_kept_exposure_is_not_a_contradiction(self):
        # Lau wants to retain Hong Kong property; Lindqvist keeps a stake in his former business.
        kinds = {d["kind"] for d in _detection(self.bundle, "CL-0014")["detections"]}
        self.assertNotIn("wealth_concentration", kinds)
        self.assertEqual(_detection(self.bundle, "CL-0009")["detections"], [])

    def test_labels_carry_no_unsupported_numbers(self):
        for card in self.queue.values():
            self.assertIsNone(re.search(r"\d", card["tension"]), card["tension"])

    def test_queue_cards_cite_where_the_contradiction_came_from(self):
        for card in self.queue.values():
            if card["detections"]:
                self.assertTrue(card["detected_from"])
                self.assertEqual(card["tension"], card["detections"][0]["label"])

    def test_client_page_tells_the_same_story_as_the_queue(self):
        ravi = self.payload["client_profiles"]["CL-0002"]
        card = self.queue["CL-0002"]
        self.assertTrue(ravi["tension"]["portfolio_does"].startswith(card["detections"][0]["evidence"]))
        self.assertEqual(ravi["headline_metrics"][0]["label"], "linked to technology")
        self.assertIn(card["tension"].lower(), ravi["conversation"]["open"])

    def test_a_new_client_is_detected_without_a_rule(self):
        instruments = self.bundle["instruments"]
        client = SimpleNamespace(
            client_id="CL-9999",
            source_of_wealth="Entrepreneur - founder of a semiconductor design company",
            objectives="Diversify away from the founding business; fund a home purchase in 2028",
            risk_profile="Balanced",
            risk_tolerance_score=5,
            liquidity_needs="Low",
            life_stage="Post-liquidity event",
        )
        positions = {"SYN-ST-0102": 6_000_000, "SYN-EQ-0003": 2_000_000, "SYN-EQ-0001": 1_500_000, "SYN-CA-0601": 500_000}
        rows = []
        for instrument_id, value in positions.items():
            ref = instruments[instruments.instrument_id == instrument_id].iloc[0]
            rows.append({
                "instrument_id": instrument_id,
                "instrument_name": ref.instrument_name,
                "asset_class": ref.asset_class,
                "instrument_ccy": ref.currency,
                "liquidity_tier": ref.liquidity_tier,
                "market_value_usd": value,
            })
        result = detect(client, pd.DataFrame(rows), instruments, [], 0.0, [], "2026-08-26")
        self.assertEqual(result["primary"]["kind"], "wealth_concentration")
        self.assertEqual(result["primary"]["label"], "Diversification goal vs technology exposure")
        self.assertAlmostEqual(result["theme_exposure_pct"], 80.0)
        self.assertGreater(result["goal_points"], 30)


if __name__ == "__main__":
    unittest.main()
