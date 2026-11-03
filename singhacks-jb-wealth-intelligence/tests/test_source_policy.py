import unittest

from tessera.source_policy import news_source_policy, safe_source_url


class SourcePolicyTests(unittest.TestCase):
    def test_direct_publishers_use_domain_boundaries(self):
        self.assertEqual(news_source_policy("https://www.cnbc.com/story"), "allowlisted_publisher")
        for url in ("https://cnbc.com.attacker.test/story", "https://notcnbc.com/story",
                    "https://attacker.test/cnbc.com", "https://www.cnbc.com@attacker.test/story"):
            self.assertEqual(news_source_policy(url), "unreviewed_publisher", url)

    def test_aggregated_results_need_an_allowed_original_publisher_url(self):
        google = "https://news.google.com/rss/articles/story"
        self.assertEqual(news_source_policy(google), "unreviewed_publisher")
        self.assertEqual(news_source_policy(google, "https://www.reuters.com"), "allowlisted_publisher")
        self.assertEqual(news_source_policy(google, "https://unreviewed.test"), "unreviewed_publisher")

    def test_unsafe_or_invalid_urls_are_never_rendered_as_source_links(self):
        for url in ("javascript:alert(1)", "data:text/html,test", "http://www.cnbc.com", "https://[bad",
                    "https://user:password@www.cnbc.com", None, float("nan")):
            self.assertIsNone(safe_source_url(url), str(url))
