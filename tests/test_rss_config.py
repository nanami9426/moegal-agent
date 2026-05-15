import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.rss_pipeline.feeds import get_configured_feed_urls


class RssConfigTest(unittest.TestCase):
    def test_builds_rsshub_urls_from_config_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "rss_feeds.txt"
            config_path.write_text(
                "\n".join(
                    [
                        "# comment",
                        "/bangumi.tv/calendar/today",
                        "bilibili/user/video/123",
                        "https://example.com/feed.xml?foo=bar",
                    ]
                ),
                encoding="utf-8",
            )

            with (
                patch("services.rss_pipeline.feeds.RSS_FEEDS_CONFIG_PATH", config_path),
                patch.dict(
                    os.environ,
                    {
                        "MOEGAL_RSSHUB_BASE_URL": "127.0.0.1:1200",
                        "MOEGAL_RSSHUB_ACCESS_KEY": "moegal_rsshub",
                    },
                    clear=True,
                ),
            ):
                urls = get_configured_feed_urls()

        self.assertEqual(
            urls,
            [
                "http://127.0.0.1:1200/bangumi.tv/calendar/today?key=moegal_rsshub",
                "http://127.0.0.1:1200/bilibili/user/video/123?key=moegal_rsshub",
                "https://example.com/feed.xml?foo=bar&key=moegal_rsshub",
            ],
        )


if __name__ == "__main__":
    unittest.main()
