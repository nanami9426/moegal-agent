import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

from services.rss_pipeline.feeds import collect


class RssFeedsTest(unittest.TestCase):
    def test_collect_parses_rss_and_namespaces_guid(self) -> None:
        source = _source("source-one", "https://example.com/feed.xml")
        client = _client(
            b"""
            <rss version="2.0"><channel><title>Example Feed</title>
              <item><guid>42</guid><title>Example</title>
                <link>https://example.com/items/42</link>
                <description><![CDATA[<p>Hello&nbsp;world</p>]]></description>
                <pubDate>Sun, 30 Aug 2026 08:00:00 GMT</pubDate>
              </item>
            </channel></rss>
            """
        )

        entries = collect(source, client)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].entry_id, "feed:source-one:42")
        self.assertEqual(entries[0].summary, "Hello world")
        self.assertEqual(
            entries[0].published_at,
            datetime(2026, 8, 30, 8, tzinfo=timezone.utc),
        )
        self.assertEqual(entries[0].raw["source_key"], "source-one")
        client.get.assert_called_once_with("https://example.com/feed.xml")

    def test_collect_parses_atom(self) -> None:
        source = _source("atom-source", "https://example.com/atom.xml")
        client = _client(
            b"""
            <feed xmlns="http://www.w3.org/2005/Atom">
              <title>Atom Feed</title>
              <entry><id>tag:example.com,2026:1</id><title>Atom Item</title>
                <link href="https://example.com/atom/1"/>
                <updated>2026-08-30T09:30:00Z</updated>
              </entry>
            </feed>
            """
        )

        entries = collect(source, client)

        self.assertEqual(entries[0].entry_id, "feed:atom-source:tag:example.com,2026:1")
        self.assertEqual(entries[0].link, "https://example.com/atom/1")

    def test_collect_rejects_unparseable_feed(self) -> None:
        source = _source("broken", "https://example.com/broken.xml")

        with self.assertRaisesRegex(ValueError, "无法解析"):
            collect(source, _client(b"not xml"))


def _source(source_id: str, url: str) -> SimpleNamespace:
    return SimpleNamespace(id=source_id, kind="feed", options={"url": url})


def _client(content: bytes) -> Mock:
    response = Mock()
    response.content = content
    response.raise_for_status.return_value = None
    client = Mock()
    client.get.return_value = response
    return client


if __name__ == "__main__":
    unittest.main()
