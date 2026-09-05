import io
import json
import unittest
from unittest import mock

from tessera.evaluation import _call_judge, _message_text, _parse_judgement


JUDGEMENT = {
    "verdict": "support_for_rm_review",
    "score": 81,
    "customer_fit": 82,
    "product_fit": 80,
    "signal_support": 76,
    "unsupported_claims": [],
    "conflicts": [],
    "required_rm_checks": ["Confirm with the client"],
    "rationale": "The supplied evidence supports an RM review.",
}


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


class EvaluationProviderTests(unittest.TestCase):
    def test_structured_output_parser_accepts_common_provider_wrappers(self):
        encoded = json.dumps(JUDGEMENT)
        self.assertEqual(_parse_judgement(f"```json\n{encoded}\n```"), JUDGEMENT)
        self.assertEqual(_parse_judgement(f"Judgement:\n{encoded}\nDone."), JUDGEMENT)
        self.assertEqual(
            _message_text(
                {"choices": [{"message": {"content": [{"type": "text", "text": encoded}]}}]}
            ),
            encoded,
        )

    def test_judge_has_enough_output_budget_and_parses_a_valid_response(self):
        response = {"choices": [{"message": {"content": json.dumps(JUDGEMENT)}}]}
        captured = {}

        def fake_urlopen(request, timeout):
            captured.update(json.loads(request.data.decode("utf-8")))
            self.assertEqual(timeout, 22)
            return _Response(json.dumps(response).encode("utf-8"))

        with mock.patch("tessera.evaluation.urlopen", side_effect=fake_urlopen):
            result = _call_judge("anthropic/test-model", {}, "token")

        self.assertEqual(result["status"], "Completed")
        self.assertGreaterEqual(captured["max_tokens"], 2000)
        self.assertEqual(captured["reasoning"], {"effort": "none"})

    def test_truncated_json_is_retried_and_can_recover(self):
        truncated = {"choices": [{"message": {"content": '{"score": 72, "rationale": "cut'}}]}
        completed = {"choices": [{"message": {"content": json.dumps(JUDGEMENT)}}]}
        responses = iter((truncated, completed))

        def fake_urlopen(_request, timeout):
            self.assertEqual(timeout, 22)
            return _Response(json.dumps(next(responses)).encode("utf-8"))

        with mock.patch("tessera.evaluation.urlopen", side_effect=fake_urlopen) as request:
            result = _call_judge("google/test-model", {}, "token")

        self.assertEqual(result["status"], "Completed")
        self.assertEqual(request.call_count, 2)

    def test_two_truncated_responses_return_a_clear_status(self):
        response = {"choices": [{"message": {"content": '{"score": 72, "rationale": "cut'}}]}

        def fake_urlopen(_request, _timeout=None, **_kwargs):
            return _Response(json.dumps(response).encode("utf-8"))

        with mock.patch("tessera.evaluation.urlopen", side_effect=fake_urlopen) as request:
            result = _call_judge("google/test-model", {}, "token")

        self.assertEqual(result["status"], "Incomplete response")
        self.assertEqual(request.call_count, 2)
        self.assertNotIn("Unterminated string", result["error"])
        self.assertIn("run the panel again", result["error"])


if __name__ == "__main__":
    unittest.main()
