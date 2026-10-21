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


class DeidentifiedPacketTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from pathlib import Path
        from tessera.engine import build_intelligence_payload

        cls.payload = build_intelligence_payload(Path(__file__).resolve().parents[1] / "data")
        cls.client = cls.payload["client_profiles"]["CL-0019"]

    def test_models_see_the_action_and_profile_but_not_the_client(self):
        from tessera.evaluation import _evaluation_packet

        packet = _evaluation_packet(self.client, self.client["recommendations"][0])
        encoded = json.dumps(packet)
        self.assertEqual(packet["proposed_action"]["title"], "Ring-fence the family-office seed capital")
        self.assertEqual(packet["client_profile"]["risk_profile"], "Balanced Growth")
        self.assertEqual(packet["client_profile"]["aum_band"], "USD 25-50m")
        self.assertEqual(packet["client_profile"]["detected_contradictions"][0]["kind"], "wealth_concentration")
        for private in ("Abdullah", "Mansoori", "CL-0019", "United Arab Emirates", "outside the Gulf region", "N-025", "32.21"):
            self.assertNotIn(private, encoded)

    def test_rm_edited_wording_is_withheld(self):
        from tessera.evaluation import _evaluation_packet

        edited = {**self.client["recommendations"][0], "detail": "Call Abdullah about his Dubai accounts"}
        packet = _evaluation_packet(self.client, edited)
        self.assertNotIn("detail", packet["proposed_action"])
        self.assertIn("Withheld", packet["proposed_action"]["wording"])

    def test_privacy_check_blocks_identifying_packets_before_any_model_runs(self):
        from tessera.evaluation import _evaluation_packet, evaluate_recommendation, outbound_privacy_check

        packet = _evaluation_packet(self.client, self.client["recommendations"][0])
        self.assertEqual(outbound_privacy_check(packet, self.client)["status"], "Passed")
        packet["client_profile"]["detected_contradictions"].append({"kind": "liquidity", "summary": "Abdullah Al-Mansoori CL-0019"})
        self.assertEqual(set(outbound_privacy_check(packet, self.client)["issues"]), {"client ID", "client name"})

        leaky = json.loads(json.dumps(self.payload))
        leaky["client_profiles"]["CL-0019"]["priority"]["detections"][0]["label"] = "Abdullah wants out of shipping"
        with mock.patch.dict("os.environ", {"TESSERA_EXTERNAL_JUDGES_ENABLED": "true", "AI_GATEWAY_API_KEY": "key"}), \
                mock.patch("tessera.evaluation._call_judge") as judge:
            result = evaluate_recommendation(leaky, "CL-0019", 0)
        judge.assert_not_called()
        self.assertEqual(result["privacy_check"]["status"], "Blocked")
        self.assertTrue(all("privacy check blocked" in j["reason"] for j in result["judges"]))

    def test_evaluation_records_what_was_sent(self):
        from tessera.evaluation import evaluate_recommendation
        from tessera.recommendation_validation import fingerprint

        result = evaluate_recommendation(self.payload, "CL-0019", 0)
        self.assertEqual(result["packet_fingerprint"], fingerprint(result["packet"]))
        self.assertEqual(result["privacy_check"]["status"], "Passed")


if __name__ == "__main__":
    unittest.main()
