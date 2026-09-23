import json
import unittest
import unittest.mock

from scripts import fetch_data as fd

CBR = json.dumps({
    "Date": "2026-09-23T11:30:00+03:00",
    "Valute": {
        "USD": {"Nominal": 1, "Value": 92.5, "Previous": 92.0},
        "EUR": {"Nominal": 1, "Value": 100.0, "Previous": 101.0},
        "CNY": {"Nominal": 10, "Value": 128.0, "Previous": 127.0},
    },
})

YAHOO = json.dumps({"chart": {"result": [{
    "meta": {"regularMarketPrice": 71.3},
    "indicators": {"quote": [{"close": [70.0, None, 70.5, 71.3]}]},
}]}})

RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<item><title>Old news</title><link>https://example.com/old</link>
<pubDate>Mon, 21 Sep 2026 10:00:00 +0300</pubDate></item>
<item><title>Fresh &amp;quot;news&amp;quot;</title><link>https://example.com/new</link>
<pubDate>Wed, 23 Sep 2026 09:00:00 GMT</pubDate></item>
<item><title>Evil</title><link>javascript:alert(1)</link>
<pubDate>Wed, 23 Sep 2026 09:00:00 GMT</pubDate></item>
</channel></rss>"""

ATOM = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>Atom story</title>
<link rel="alternate" type="text/html" href="https://example.org/story"/>
<published>2026-09-23T08:00:00Z</published></entry>
</feed>"""


class RatesTests(unittest.TestCase):
    def test_rates_are_per_one_unit_even_when_cbr_quotes_per_ten(self):
        items = {i["id"]: i for i in fd.parse_cbr(CBR)["items"]}
        self.assertAlmostEqual(items["CNY"]["value"], 12.8)
        self.assertAlmostEqual(items["CNY"]["change"], 0.1)

    def test_rate_change_is_difference_from_previous_day(self):
        items = {i["id"]: i for i in fd.parse_cbr(CBR)["items"]}
        self.assertAlmostEqual(items["USD"]["change"], 0.5)
        self.assertAlmostEqual(items["EUR"]["change"], -1.0)


class CommodityTests(unittest.TestCase):
    def test_yahoo_change_is_against_previous_close_skipping_gaps(self):
        price, change = fd.parse_yahoo_chart(YAHOO)
        self.assertEqual(price, 71.3)
        self.assertEqual(change, 0.8)

    def test_stooq_gives_price_without_change(self):
        raw = b"Symbol,Date,Time,Close\r\nCB.F,2026-09-23,10:00:00,71.25\r\n"
        self.assertEqual(fd.parse_stooq_csv(raw), (71.25, None))

    def test_stooq_unknown_ticker_is_an_error_not_zero(self):
        raw = b"Symbol,Date,Time,Close\r\nXX.F,N/D,N/D,N/D\r\n"
        with self.assertRaises(ValueError):
            fd.parse_stooq_csv(raw)


class NewsTests(unittest.TestCase):
    def test_rss_and_atom_are_both_understood(self):
        rss = fd.parse_feed(RSS, "A")
        atom = fd.parse_feed(ATOM, "B")
        self.assertEqual(atom, [{"title": "Atom story", "link": "https://example.org/story",
                                 "source": "B", "published": "2026-09-23T08:00:00Z"}])
        self.assertEqual(rss[0]["published"], "2026-09-21T07:00:00Z")

    def test_double_escaped_titles_are_readable(self):
        titles = [n["title"] for n in fd.parse_feed(RSS, "A")]
        self.assertIn('Fresh "news"', titles)

    def test_non_http_links_are_dropped(self):
        links = [n["link"] for n in fd.parse_feed(RSS, "A")]
        self.assertNotIn("javascript:alert(1)", links)
        self.assertEqual(len(links), 2)

    def test_merged_news_are_newest_first_and_one_feed_cannot_flood(self):
        noisy = [{"title": str(i), "link": "https://x", "source": "noisy",
                  "published": f"2026-09-23T{i:02d}:00:00Z"} for i in range(20)]
        quiet = [{"title": "q", "link": "https://y", "source": "quiet",
                  "published": "2026-09-22T00:00:00Z"}]
        merged = fd.merge_news([noisy, quiet])
        self.assertEqual(sum(n["source"] == "noisy" for n in merged), fd.NEWS_PER_FEED)
        self.assertEqual(merged[-1]["source"], "quiet")
        self.assertEqual(merged[0]["title"], "19")


class BuildTests(unittest.TestCase):
    def test_one_broken_source_does_not_break_the_others(self):
        def broken():
            raise RuntimeError("сайт лежит")
        data = fd.build({"ok": lambda: {"items": [1]}, "bad": broken}, {}, "T")
        self.assertEqual(data["ok"]["items"], [1])
        self.assertEqual(data["bad"]["items"], [])
        self.assertIn("error", data["bad"])

    def test_failed_section_falls_back_to_previous_data_marked_stale(self):
        def broken():
            raise RuntimeError("сайт лежит")
        previous = {"bad": {"items": [42], "updated": "OLD"}}
        data = fd.build({"bad": broken}, previous, "NEW")
        self.assertEqual(data["bad"], {"items": [42], "updated": "OLD", "stale": True})

    def test_schedule_without_credentials_says_it_is_not_connected(self):
        with unittest.mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(fd.fetch_schedule()["items"], [])


if __name__ == "__main__":
    unittest.main()
