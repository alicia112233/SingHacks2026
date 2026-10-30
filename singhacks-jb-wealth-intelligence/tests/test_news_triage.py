import json
import unittest
from pathlib import Path
from unittest import mock

from tessera import news_triage
from tessera.engine import _live_event_relevance, build_intelligence_payload
from tessera.escalation import headline_topics
from tessera.evaluation import evaluate_recommendation


class _Response:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return self.body


class NewsTriageTests(unittest.TestCase):
    def test_only_public_headline_fields_leave_tessera(self):
        batch = news_triage.public_batch([{"description": "Oil jumps", "publisher": "CNBC", "event_date": "2026-10-29", "source": "https://x", "client_id": "CL-0019"}])
        self.assertEqual(set(batch[0]), {"index", "description", "publisher", "event_date"})

    def test_majority_vote_decides_topics_and_median_severity(self):
        votes = [
            {"relevant": True, "topics": ["shipping", "energy"], "severity": "Severe"},
            {"relevant": True, "topics": ["shipping"], "severity": "High"},
            {"relevant": False, "topics": [], "severity": "Low"},
        ]
        result = news_triage.combine(votes, ["a", "b", "c"])
        self.assertTrue(result["relevant"])
        self.assertEqual(result["topics"], ["shipping"])
        self.assertEqual(result["severity"], "High")
        self.assertEqual(result["agreement"], "1 of 3 models agree on severity")

    def test_irrelevant_headlines_get_no_topics(self):
        votes = [{"relevant": False, "topics": ["gold"], "severity": "Low"}] * 2
        self.assertEqual(news_triage.combine(votes, ["a", "b"])["topics"], [])

    def test_triage_overrides_keyword_severity_and_skips_done_events(self):
        events = [{"description": "Gold dips as Golden Harbour reports", "severity": "High"}, {"description": "Old", "triage": {}}]
        answer = {0: {"relevant": True, "topics": [], "severity": "Low"}}
        with mock.patch.dict("os.environ", {"TESSERA_NEWS_TRIAGE_ENABLED": "true", "AI_GATEWAY_API_KEY": "key"}), \
                mock.patch("tessera.news_triage._ask", return_value=answer) as ask:
            self.assertEqual(news_triage.triage(events), 1)
        self.assertEqual(ask.call_count, 3)
        self.assertEqual(events[0]["severity"], "Low")
        self.assertEqual(events[0]["keyword_severity"], "High")
        self.assertEqual(events[0]["topics"], [])

    def test_triage_is_off_by_default(self):
        with mock.patch.dict("os.environ", {"AI_GATEWAY_API_KEY": "key"}, clear=True), mock.patch("tessera.news_triage._ask") as ask:
            self.assertEqual(news_triage.triage([{"description": "Oil jumps"}]), 0)
        ask.assert_not_called()

    def test_triaged_topics_replace_keyword_matching(self):
        self.assertEqual([t[0] for t in headline_topics("gold rallies")], ["gold"])
        self.assertEqual(headline_topics("gold rallies", []), [])
        self.assertEqual([t[0] for t in headline_topics("markets steady", ["shipping"])], ["shipping"])
        self.assertEqual(_live_event_relevance("oil spikes", "global energy majors fund", []), 0)
        self.assertEqual(_live_event_relevance("markets steady", "global energy majors fund", ["energy"]), 2)


class InHouseReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = build_intelligence_payload(Path(__file__).resolve().parents[1] / "data")

    def test_one_model_reviews_from_three_angles_on_a_local_endpoint(self):
        judgement = {"verdict": "support_for_rm_review", "score": 80, "customer_fit": 80, "product_fit": 80, "signal_support": 80,
                     "unsupported_claims": [], "conflicts": [], "required_rm_checks": [], "rationale": "ok"}
        calls = []

        def fake_urlopen(request, timeout):
            calls.append((request.full_url, request.headers, json.loads(request.data)))
            return _Response(json.dumps({"choices": [{"message": {"content": json.dumps(judgement)}}]}).encode("utf-8"))

        env = {"TESSERA_INHOUSE_REVIEW_ENABLED": "true", "TESSERA_INHOUSE_URL": "http://localhost:11434/v1/chat/completions", "TESSERA_INHOUSE_MODEL": "llama3"}
        with mock.patch.dict("os.environ", env, clear=True), mock.patch("tessera.evaluation.urlopen", side_effect=fake_urlopen):
            result = evaluate_recommendation(self.payload, "CL-0019", 0)
        self.assertEqual(len(calls), 3)
        self.assertTrue(all(url == env["TESSERA_INHOUSE_URL"] and "Authorization" not in headers for url, headers, _ in calls))
        self.assertEqual({body["model"] for *_, body in calls}, {"llama3"})
        self.assertEqual(sorted(body["messages"][0]["content"].split(":")[0] for *_, body in calls),
                         ["Focus on client fit", "Focus on evidence quality", "Focus on suitability and compliance"])
        self.assertEqual([j["angle"] for j in result["judges"]], ["Suitability and compliance", "Client fit", "Evidence quality"])
        self.assertEqual(result["reviewer"]["deployment"], "Local in-house model")


if __name__ == "__main__":
    unittest.main()
