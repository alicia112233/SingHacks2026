import io
import json
import shutil
import threading
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from xml.etree.ElementTree import Element, SubElement

from tessera.engine import build_intelligence_payload
from tessera.market_news import _approved_event, _feed_urls, refresh


ROOT = Path(__file__).resolve().parents[1]


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


class MarketNewsTests(unittest.TestCase):
    def test_default_feeds_include_yahoo_cnbc_and_google(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            feeds = _feed_urls()
        self.assertEqual(feeds[:2], (
            "https://finance.yahoo.com/rss/topstories",
            "https://www.cnbc.com/id/100003114/device/rss/rss.html",
        ))
        self.assertEqual(feeds[2], "https://www.businesstimes.com.sg/rss/companies-markets")
        self.assertEqual(len(feeds), 10)
        self.assertTrue(all(url.startswith("https://news.google.com/rss/search?q=") for url in feeds[3:]))
        for domain in ("wealthbriefingasia.com", "ft.com", "asia.nikkei.com", "channelnewsasia.com"):
            self.assertTrue(any(domain in url for url in feeds[3:]), domain)

    def test_html_summary_becomes_plain_headline(self):
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

    def test_publisher_is_kept_for_source_attribution(self):
        item = Element("item")
        SubElement(item, "title").text = "Oil shipping market surges"
        SubElement(item, "link").text = "https://example.test/story"
        SubElement(item, "source").text = "Financial Times"
        self.assertEqual(_approved_event(item)["publisher"], "Financial Times")
        self.assertEqual(_approved_event(item, "The Business Times")["publisher"], "Financial Times")
        item.remove(item.find("source"))
        self.assertEqual(_approved_event(item, "The Business Times")["publisher"], "The Business Times")

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
            modified_at = state.stat().st_mtime_ns
            second = refresh(ROOT / "data", state)
            self.assertEqual(state.stat().st_mtime_ns, modified_at)
        self.assertEqual(first["added"], 1)
        self.assertEqual(second["added"], 0)
        self.assertEqual(first["events"][0]["status"], "approved")
        self.assertEqual(first["events"][0]["source_type"], "live_news")

    def test_refresh_preserves_existing_google_news_events(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(
            "os.environ", {"TESSERA_NEWS_FEEDS": "https://example.test/feed"}, clear=True
        ), mock.patch("tessera.market_news.urlopen", return_value=Response(b"<rss><channel/></rss>")):
            state = Path(directory) / "live_events.json"
            state.write_text(json.dumps([{
                "event_id": "rss:legacy", "source": "https://news.google.com/rss/articles/legacy",
                "description": "Legacy Google story",
            }]), encoding="utf-8")
            result = refresh(ROOT / "data", state)
        self.assertEqual(result["events"][0]["event_id"], "rss:legacy")

    def test_feed_fetches_do_not_wait_for_each_other(self):
        barrier = threading.Barrier(2)

        def fetch(_request, timeout):
            self.assertEqual(timeout, 8)
            barrier.wait(timeout=2)
            return Response(b"<rss><channel/></rss>")

        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(
            "os.environ", {"TESSERA_NEWS_FEEDS": "https://example.test/one,https://example.test/two"}, clear=True
        ), mock.patch("tessera.market_news.urlopen", side_effect=fetch):
            result = refresh(ROOT / "data", Path(directory) / "live_events.json")
        self.assertEqual(result["status"], "refreshed")

    def test_one_unavailable_feed_does_not_hide_the_other(self):
        rss = b'<rss><channel><item><guid>cnbc-1</guid><title>Oil shipping market risk surges</title><link>https://www.cnbc.com/story</link></item></channel></rss>'
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(
            "os.environ", {"TESSERA_LIVE_NEWS_ENABLED": "true", "TESSERA_NEWS_FEEDS": "https://finance.yahoo.com/rss/topstories,https://www.cnbc.com/id/100003114/device/rss/rss.html"}, clear=True
        ), mock.patch("tessera.market_news.urlopen", side_effect=[OSError("Yahoo unavailable"), Response(rss)]):
            result = refresh(ROOT / "data", Path(directory) / "live_events.json")
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["added"], 1)

    def test_controlled_baseline_ignores_saved_live_news_by_default(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(
            "os.environ", {}, clear=True
        ):
            data_dir = Path(directory) / "data"
            shutil.copytree(ROOT / "data", data_dir)
            state = Path(directory) / "runtime" / "live_events.json"
            state.parent.mkdir()
            state.write_text(json.dumps([{
                "event_id": "rss:isolated", "event_date": "2026-09-01",
                "event_type": "Live market signal", "region": "Global",
                "description": "Shipping energy shock",
                "primary_transmission": "Energy, shipping, rates and risk assets",
                "severity": "Severe", "source": "https://example.test/story",
                "source_type": "live_news", "status": "approved",
            }]), encoding="utf-8")
            controlled = build_intelligence_payload(data_dir)
            with_news = build_intelligence_payload(data_dir, state)
        self.assertEqual(controlled["market_signal"]["date"], "2026-08-05")
        self.assertEqual(with_news["market_signal"]["date"], "2026-09-01")

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

    def test_live_events_update_every_client_with_portfolio_relevance(self):
        stories = [
            ("global", "Global stock market selloff hits equity funds", "High"),
            ("energy", "Oil shipping routes face disruption", "Severe"),
            ("macro1", "Global markets decline during volatile trading", "High"),
            ("macro2", "Equities retreat across global markets", "High"),
            ("macro3", "Global market indexes edge lower", "High"),
            ("consumer", "Best high-yield savings interest rates today", "High"),
        ]
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(
            "os.environ", {"TESSERA_LIVE_NEWS_ENABLED": "true"}, clear=True
        ):
            state = Path(directory) / "live_events.json"
            state.write_text(json.dumps([
                {
                    "event_id": f"rss:{name}", "event_date": "2026-09-21",
                    "event_type": "Live market signal", "region": "Global",
                    "description": description, "primary_transmission": "Global risk assets",
                    "severity": severity, "source": f"https://example.test/{name}",
                    "source_type": "live_news", "status": "approved",
                }
                for name, description, severity in stories
            ]), encoding="utf-8")
            updated = build_intelligence_payload(ROOT / "data", state)

        profiles = updated["client_profiles"]
        self.assertEqual(len(profiles), 20)
        energy_clients = set()
        for client_id, profile in profiles.items():
            urls = {event["source_url"] for event in profile["linked_events"]}
            self.assertIn("https://example.test/global", urls, client_id)
            if "https://example.test/energy" in urls:
                energy_clients.add(client_id)
                self.assertIn("https://example.test/energy", {
                    event["source_url"] for event in profile["linked_events"][-3:]
                })
            self.assertFalse(any("savings interest rates" in event["description"]
                                 for event in profile["linked_events"]))
        self.assertEqual(energy_clients, {"CL-0001", "CL-0005", "CL-0012", "CL-0015", "CL-0019"})
        pressure = {
            card["client_id"]: card["market_event_pressure"]
            for card in updated["book"]["priority_queue"]
        }
        self.assertEqual(set(pressure), set(profiles))
        self.assertTrue(all(value == (8 if client_id in energy_clients else 5)
                            for client_id, value in pressure.items()))


if __name__ == "__main__":
    unittest.main()
