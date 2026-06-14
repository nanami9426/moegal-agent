import os
import threading
import unittest
from unittest.mock import patch

from services.rss_pipeline.feeds import fetch_rss_entries


class RssFeedsTest(unittest.TestCase):
    def test_fetch_rss_entries_fetches_sources_concurrently(self) -> None:
        first_started = threading.Event()
        second_started = threading.Event()

        def fake_get(url: str, **kwargs: object) -> _FakeResponse:
            self.assertTrue(kwargs["follow_redirects"])
            self.assertEqual(kwargs["timeout"], 15.0)

            if url == "https://example.com/one.xml":
                first_started.set()
                self.assertTrue(
                    second_started.wait(timeout=1.0),
                    "second feed request did not start while first was still running",
                )
            else:
                self.assertTrue(first_started.wait(timeout=1.0))
                second_started.set()

            return _FakeResponse(_rss_bytes(url))

        with (
            patch.dict(os.environ, {"MOEGAL_RSS_FETCH_CONCURRENCY": "2"}),
            patch("services.rss_pipeline.feeds.httpx.get", side_effect=fake_get),
        ):
            result = fetch_rss_entries(
                [
                    "https://example.com/one.xml",
                    "https://example.com/two.xml",
                ]
            )

        self.assertEqual(result.errors, [])
        self.assertEqual([entry.entry_id for entry in result.entries], ["one", "two"])


class _FakeResponse:
    def __init__(self, content: bytes) -> None:
        self.content = content

    def raise_for_status(self) -> None:
        return None


def _rss_bytes(url: str) -> bytes:
    entry_id = "one" if url.endswith("one.xml") else "two"
    return f"""
        <?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
            <channel>
                <title>Example Feed</title>
                <item>
                    <guid>{entry_id}</guid>
                    <title>{entry_id}</title>
                    <link>https://example.com/{entry_id}</link>
                    <description>summary</description>
                </item>
            </channel>
        </rss>
    """.encode()


if __name__ == "__main__":
    unittest.main()
