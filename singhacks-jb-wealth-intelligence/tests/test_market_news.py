import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from xml.etree.ElementTree import Element, SubElement

from tessera.engine import build_intelligence_payload
from tessera.market_news import _approved_event, refresh


ROOT = Path(__file__).resolve().parents[1]


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


class MarketNewsTests(unittest.TestCase):
    def test_google_news_html_becomes_plain_headline(self):
        item = Element("item")
        SubElement(item, "title").text = (
            "Federal Reserve Rate Hike to 3.75%-4.00% and Global Market Impact - Kalkine India"
        )
        SubElement(item, "description").text = (
            "Federal Reserve Rate Hike to 3.75%-4.00% and Global Market Impact - Kalkine India "
            '<a href="https://example.test">Federal Reserve Rate Hike to 3.75%-4.00% and Global Market Impact</a>'
        )
        SubElement(item, "link").text = "https://example.test"
        event = _approved_event(item)
        self.assertEqual(
            event["description"],
            "Federal Reserve Rate Hike to 3.75%-4.00% and Global Market Impact",
        )
        self.assertNotIn("<a", event["description"])

    def test_refresh_approves_relevant_rss_and_deduplicates(self):
        rss = b'''<?xml version="1.0"?><rss><channel><item>
            <guid>story-1</guid><title>Oil shipping market risk surges</title>
            <description>Energy yields rise as shipping routes face disruption.</description>
            <link>https://example.test/story-1</link>
            <pubDate>Sat, 19 Sep 2026 08:00:00 GMT</pubDate>
        </item><item><guid>story-2</guid><title>Local sports result</title>
            <description>A team wins a match.</description><link>https://example.test/story-2</link>
        </item></channel></rss>'''
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(
            "os.environ",
            {"TESSERA_LIVE_NEWS_ENABLED": "true", "TESSERA_NEWS_FEEDS": "https://example.test/feed"},
            clear=True,
        ), mock.patch(
            "tessera.market_news.urlopen",
            side_effect=[Response(rss), Response(rss)],
        ):
            state = Path(directory) / "live_events.json"
            first = refresh(ROOT / "data", state)
            second = refresh(ROOT / "data", state)
        self.assertEqual(first["added"], 1)
        self.assertEqual(second["added"], 0)
        self.assertEqual(first["events"][0]["status"], "approved")
        self.assertEqual(first["events"][0]["source_type"], "live_news")

    def test_approved_live_event_adds_bounded_pressure_to_matching_client(self):
        baseline = build_intelligence_payload(ROOT / "data")
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(
            "os.environ", {"TESSERA_LIVE_NEWS_ENABLED": "true"}, clear=True
        ):
            state = Path(directory) / "live_events.json"
            state.write_text(
                json.dumps([
                    {
                        "event_id": "rss:pressure",
                        "event_date": "2026-09-01",
                        "event_type": "Live market signal",
                        "region": "Global",
                        "description": "Shipping energy shock",
                        "primary_transmission": "Energy, shipping, rates and risk assets",
                        "severity": "Severe",
                        "source": "https://example.test/pressure",
                        "source_type": "live_news",
                        "status": "approved",
                    }
                ]),
                encoding="utf-8",
            )
            updated = build_intelligence_payload(ROOT / "data", state)
        base_score = next(item["score"] for item in baseline["book"]["priority_queue"] if item["client_id"] == "CL-0019")
        updated_card = next(item for item in updated["book"]["priority_queue"] if item["client_id"] == "CL-0019")
        self.assertEqual(updated_card["market_event_pressure"], 8)
        self.assertEqual(updated_card["score"], base_score + 8)


if __name__ == "__main__":
    unittest.main()