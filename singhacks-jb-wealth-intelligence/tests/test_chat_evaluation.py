import unittest
import json
import tempfile
from pathlib import Path

from tessera.chat_evaluation import evaluate_chat


class ChatEvaluationTests(unittest.TestCase):
    def test_frozen_answer_key_and_adversarial_cases_pass(self):
        report = evaluate_chat(Path(__file__).resolve().parents[1] / "evals" / "chat_grounding.v1.json")
        self.assertTrue(report["passed"], [row["id"] for row in report["cases"] if not row["passed"]])
        self.assertFalse(report["live_model_evaluated"])
        self.assertFalse(report["independent_source_truth_verified"])

    def test_a_wrong_answer_key_fails_the_evaluation(self):
        root = Path(__file__).resolve().parents[1]
        fixture = json.loads((root / "evals" / "chat_grounding.v1.json").read_text(encoding="utf-8"))
        fixture["cases"] = [fixture["cases"][0]]
        fixture["cases"][0]["contains"] = ["USD 999m"]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.json"
            path.write_text(json.dumps(fixture), encoding="utf-8")
            report = evaluate_chat(path, root / "data")
        self.assertFalse(report["passed"])
        self.assertEqual(report["metrics"]["numerical_answer_key_match"]["passed"], 0)
