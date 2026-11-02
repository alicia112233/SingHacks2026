from pathlib import Path
import re
import unittest

from tessera.client_vector import FEATURES, KEYS, _cosine, _scaled, build_client_vectors
from tessera.engine import _cash_need_summary, _detection, build_intelligence_payload, load_dataset

ROOT = Path(__file__).resolve().parents[1]


class ClientVectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = load_dataset(ROOT / "data")
        cls.needs = {cid: _cash_need_summary(cls.bundle, cid) for cid in cls.bundle["clients"].client_id}
        cls.vectors = build_client_vectors(cls.bundle, cls.needs)
        cls.clients = cls.vectors["clients"]

    def test_same_data_gives_same_vectors(self):
        self.assertEqual(build_client_vectors(self.bundle, self.needs), self.vectors)

    def test_every_client_has_every_named_feature(self):
        self.assertEqual(len(self.clients), 20)
        for vector in self.clients.values():
            self.assertEqual(list(vector["values"]), KEYS)
        self.assertEqual(len({f.key for f in FEATURES}), len(FEATURES))

    def test_similar_clients_exclude_self_and_are_ranked(self):
        for cid, vector in self.clients.items():
            scores = [item["similarity"] for item in vector["similar"]]
            self.assertEqual(len(scores), 3)
            self.assertNotIn(cid, [item["client_id"] for item in vector["similar"]])
            self.assertEqual(scores, sorted(scores, reverse=True))
            self.assertTrue(all(-1 <= score <= 1 for score in scores))

    def test_similarity_is_symmetric_and_self_is_one(self):
        raw = __import__("pandas").DataFrame({cid: v["values"] for cid, v in self.clients.items()}).T[KEYS]
        matrix = _cosine(_scaled(raw))
        self.assertTrue(((matrix - matrix.T).abs() < 1e-9).all().all())
        for cid in matrix.index:
            self.assertAlmostEqual(matrix.at[cid, cid], 1.0)

    def test_one_large_position_cannot_swamp_the_vector(self):
        raw = __import__("pandas").DataFrame({cid: v["values"] for cid, v in self.clients.items()}).T[KEYS]
        # Ranking bounds every scaled value, however large the raw number.
        self.assertLessEqual(float(_scaled(raw).abs().max().max()), 0.5)

    def test_shared_reasons_are_true_for_both_clients(self):
        for cid, vector in self.clients.items():
            for item in vector["similar"]:
                for reason in item["shared"]:
                    self.assertEqual(reason["a"], vector["values"][reason["key"]])
                    self.assertEqual(reason["b"], self.clients[item["client_id"]]["values"][reason["key"]])

    def test_abdullah_drifts_towards_what_he_asked_to_leave(self):
        abdullah = self.clients["CL-0019"]
        self.assertEqual(abdullah["goal_themes"], "energy and shipping")
        gap = [point["pct"] for point in abdullah["goal_gap"]]
        self.assertEqual(len(gap), 5)
        self.assertLess(gap[0], gap[-1])
        self.assertAlmostEqual(gap[-1], _detection(self.bundle, "CL-0019")["theme_exposure_pct"])

    def test_clients_without_a_stated_exit_have_no_goal_gap(self):
        self.assertIsNone(self.clients["CL-0002"]["goal_gap"])

    def test_module_names_no_client_and_calls_no_network(self):
        source = (ROOT / "tessera" / "client_vector.py").read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"CL-\d{4}", source))
        self.assertIsNone(re.search(r"urllib|requests|http|socket|retrieval|evaluation", source))

    def test_payload_carries_vectors_and_a_map(self):
        payload = build_intelligence_payload(ROOT / "data")
        vectors = payload["client_vectors"]
        self.assertEqual(vectors["as_of"], "2026-08-26")
        self.assertEqual(set(vectors["axes"]), {"x", "y"})
        for vector in vectors["clients"].values():
            self.assertTrue(-1 <= vector["map"]["x"] <= 1 and -1 <= vector["map"]["y"] <= 1)
        self.assertNotIn("client_vector", payload["client_profiles"]["CL-0019"])


if __name__ == "__main__":
    unittest.main()
