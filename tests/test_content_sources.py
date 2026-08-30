import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from services.rss_pipeline.sources import (
    CONTENT_SOURCES_CONFIG_PATH,
    ContentSource,
    collect_content_sources,
    load_content_sources,
)


class ContentSourceConfigTest(unittest.TestCase):
    def test_default_config_has_sixteen_enabled_sources(self) -> None:
        sources = load_content_sources()

        self.assertEqual(CONTENT_SOURCES_CONFIG_PATH.name, "content_sources.toml")
        self.assertEqual(len(sources), 16)
        self.assertNotIn("example-feed", {source.id for source in sources})
        self.assertEqual(
            sum(source.kind == "mihoyo_official" for source in sources),
            6,
        )
        self.assertEqual(
            sum(source.kind == "bilibili_anime_timeline" for source in sources),
            1,
        )
        self.assertEqual(
            sum(source.kind == "bilibili_category_rank" for source in sources),
            2,
        )

    def test_missing_config_returns_empty_list(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            missing_path = Path(temp_dir) / "missing.toml"
            self.assertEqual(load_content_sources(missing_path), [])

    def test_loads_enabled_sources_and_flattens_kind_options(self) -> None:
        sources = self._load(
            """
            version = 1

            [[sources]]
            id = "native-feed"
            kind = "feed"
            url = "https://example.com/feed.xml"

            [[sources]]
            id = "disabled-news"
            kind = "arknights_news"
            enabled = false
            """
        )

        self.assertEqual(
            sources,
            [
                ContentSource(
                    id="native-feed",
                    kind="feed",
                    enabled=True,
                    options={"url": "https://example.com/feed.xml"},
                )
            ],
        )

    def test_rejects_invalid_version_and_unknown_top_level_field(self) -> None:
        invalid_configs = [
            "version = 2\n",
            'version = 1\nextra = "value"\n',
        ]
        for config in invalid_configs:
            with self.subTest(config=config), self.assertRaises(ValueError):
                self._load(config)

    def test_rejects_invalid_or_duplicate_source_ids(self) -> None:
        invalid_configs = [
            """
            version = 1
            [[sources]]
            id = "Invalid ID"
            kind = "bilibili_weekly"
            """,
            """
            version = 1
            [[sources]]
            id = "same-id"
            kind = "bilibili_weekly"
            [[sources]]
            id = "same-id"
            kind = "bilibili_hot_search"
            """,
        ]
        for config in invalid_configs:
            with self.subTest(config=config), self.assertRaises(ValueError):
                self._load(config)

    def test_rejects_unknown_kind_fields_and_missing_required_fields(self) -> None:
        invalid_configs = [
            """
            version = 1
            [[sources]]
            id = "unknown-kind"
            kind = "unknown"
            """,
            """
            version = 1
            [[sources]]
            id = "weekly-with-extra"
            kind = "bilibili_weekly"
            tid = 33
            """,
            """
            version = 1
            [[sources]]
            id = "feed-without-url"
            kind = "feed"
            """,
            """
            version = 1
            [[sources]]
            id = "rank-without-days"
            kind = "bilibili_category_rank"
            cate_id = 33
            """,
        ]
        for config in invalid_configs:
            with self.subTest(config=config), self.assertRaises(ValueError):
                self._load(config)

    def test_feed_requires_absolute_http_url(self) -> None:
        for url in [
            "feed.xml",
            "/feed.xml",
            "ftp://example.com/feed.xml",
            "https://example.com:bad/feed.xml",
            "https://exa mple.com/feed.xml",
        ]:
            config = f"""
                version = 1
                [[sources]]
                id = "bad-feed"
                kind = "feed"
                url = {url!r}
            """
            with self.subTest(url=url), self.assertRaises(ValueError):
                self._load(config)

    def test_validates_kind_specific_options(self) -> None:
        invalid_configs = [
            self._single_source(
                "bilibili_anime_timeline",
                "season_type = 1",
            ),
            self._single_source(
                "bilibili_category_rank",
                'cate_id = 33\ndays = 7\npage_size = 20\norder = "favorite"',
            ),
            self._single_source(
                "bilibili_category_rank",
                "cate_id = 0\ndays = 7\npage_size = 20",
            ),
            self._single_source(
                "bilibili_category_rank",
                "cate_id = 33\ndays = 31\npage_size = 20",
            ),
            self._single_source(
                "bilibili_category_rank",
                "cate_id = 33\ndays = 7\npage_size = 51",
            ),
            self._single_source("bilibili_mall_new", "category = 7"),
            self._single_source(
                "mihoyo_official",
                "gids = 1\nnews_type = 1\npage_size = 20",
            ),
            self._single_source(
                "mihoyo_official",
                "gids = 2\nnews_type = 3\npage_size = 20",
            ),
            self._single_source(
                "mihoyo_official",
                "gids = 2\nnews_type = 1\npage_size = 51",
            ),
        ]
        for config in invalid_configs:
            with self.subTest(config=config), self.assertRaises(ValueError):
                self._load(config)

    def test_accepts_timeline_with_fixed_collector_semantics(self) -> None:
        sources = self._load(
            """
            version = 1
            [[sources]]
            id = "timeline-defaults"
            kind = "bilibili_anime_timeline"
            [[sources]]
            id = "mihoyo-source"
            kind = "mihoyo_official"
            gids = 2
            news_type = 1
            page_size = 20
            """
        )

        self.assertEqual(sources[0].options, {})
        self.assertEqual(
            sources[1].options,
            {"gids": 2, "news_type": 1, "page_size": 20},
        )

    def _load(self, config: str) -> list[ContentSource]:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "content_sources.toml"
            path.write_text(config, encoding="utf-8")
            return load_content_sources(path)

    @staticmethod
    def _single_source(kind: str, options: str) -> str:
        indented_options = "\n".join(
            f"            {line}" for line in options.splitlines()
        )
        return f"""
            version = 1
            [[sources]]
            id = "test-source"
            kind = "{kind}"
{indented_options}
        """


class ContentSourceCollectionTest(unittest.TestCase):
    def test_client_uses_configured_user_agent_with_default_fallback(self) -> None:
        source = ContentSource(id="news", kind="arknights_news")
        seen_user_agents: list[str] = []

        def fake_collect(_source, client):
            seen_user_agents.append(client.headers["User-Agent"])
            return []

        for configured_value in ["Custom-Collector/2.0", "   "]:
            with (
                patch.dict(
                    os.environ,
                    {"MOEGAL_CONTENT_USER_AGENT": configured_value},
                ),
                patch(
                    "services.rss_pipeline.sources._invoke_collector",
                    side_effect=fake_collect,
                ),
            ):
                collect_content_sources([source])

        self.assertEqual(
            seen_user_agents,
            ["Custom-Collector/2.0", "Moegal-Agent/0.1"],
        )

    def test_dispatches_to_feed_and_four_platform_collectors(self) -> None:
        sources = [
            ContentSource(
                id="feed-source",
                kind="feed",
                options={"url": "https://example.com/feed.xml"},
            ),
            ContentSource(id="bangumi-source", kind="bangumi_calendar_today"),
            ContentSource(id="bilibili-source", kind="bilibili_weekly"),
            ContentSource(
                id="mihoyo-source",
                kind="mihoyo_official",
                options={"gids": 2, "news_type": 1, "page_size": 20},
            ),
            ContentSource(id="arknights-source", kind="arknights_news"),
        ]
        with (
            patch(
                "services.rss_pipeline.feeds.collect",
                return_value=["feed-entry"],
            ) as feed_collect,
            patch(
                "services.rss_pipeline.collectors.bangumi.collect",
                return_value=["bangumi-entry"],
            ) as bangumi_collect,
            patch(
                "services.rss_pipeline.collectors.bilibili.collect",
                return_value=["bilibili-entry"],
            ) as bilibili_collect,
            patch(
                "services.rss_pipeline.collectors.mihoyo.collect",
                return_value=["mihoyo-entry"],
            ) as mihoyo_collect,
            patch(
                "services.rss_pipeline.collectors.arknights.collect",
                return_value=["arknights-entry"],
            ) as arknights_collect,
        ):
            result = collect_content_sources(sources)

        self.assertEqual(
            result.entries,
            [
                "feed-entry",
                "bangumi-entry",
                "bilibili-entry",
                "mihoyo-entry",
                "arknights-entry",
            ],
        )
        self.assertEqual(result.successful_source_count, 5)
        for collector in [
            feed_collect,
            bangumi_collect,
            bilibili_collect,
            mihoyo_collect,
            arknights_collect,
        ]:
            collector.assert_called_once()

    def test_collection_keeps_source_order_and_isolates_failures(self) -> None:
        first_started = threading.Event()
        third_started = threading.Event()

        def fake_collect(source, _client):
            if source.id == "first":
                first_started.set()
                self.assertTrue(third_started.wait(timeout=1.0))
                return ["first-entry"]
            if source.id == "broken":
                raise RuntimeError("upstream failed")
            self.assertTrue(first_started.wait(timeout=1.0))
            third_started.set()
            return ["third-entry"]

        sources = [
            ContentSource(id="first", kind="bangumi_calendar_today"),
            ContentSource(id="broken", kind="feed", options={"url": "https://example.com"}),
            ContentSource(id="third", kind="arknights_news"),
        ]
        with (
            patch.dict(os.environ, {"MOEGAL_RSS_FETCH_CONCURRENCY": "3"}),
            patch(
                "services.rss_pipeline.sources._invoke_collector",
                side_effect=fake_collect,
            ),
        ):
            result = collect_content_sources(sources)

        self.assertEqual(result.entries, ["first-entry", "third-entry"])
        self.assertEqual(result.source_count, 3)
        self.assertEqual(result.successful_source_count, 2)
        self.assertEqual(len(result.errors), 1)
        self.assertEqual(result.errors[0].source_id, "broken")
        self.assertEqual(result.errors[0].source_kind, "feed")
        self.assertIn("upstream failed", result.errors[0].message)

    def test_collection_skips_disabled_sources(self) -> None:
        sources = [
            ContentSource(id="disabled", kind="bilibili_weekly", enabled=False),
        ]
        with patch("services.rss_pipeline.sources._invoke_collector") as collector:
            result = collect_content_sources(sources)

        collector.assert_not_called()
        self.assertEqual(result.source_count, 0)
        self.assertEqual(result.successful_source_count, 0)

    def test_bilibili_and_mihoyo_each_have_concurrency_limit_two(self) -> None:
        active = {"bilibili": 0, "mihoyo": 0}
        maximum = {"bilibili": 0, "mihoyo": 0}
        lock = threading.Lock()

        def fake_collect(source, _client):
            platform = (
                "bilibili" if source.kind == "bilibili_weekly" else "mihoyo"
            )
            with lock:
                active[platform] += 1
                maximum[platform] = max(maximum[platform], active[platform])
            # 短暂停留，确保线程池有机会同时调度同平台的多个来源。
            time.sleep(0.03)
            with lock:
                active[platform] -= 1
            return [source.id]

        sources = [
            *[
                ContentSource(id=f"bilibili-{index}", kind="bilibili_weekly")
                for index in range(4)
            ],
            *[
                ContentSource(
                    id=f"mihoyo-{index}",
                    kind="mihoyo_official",
                    options={"gids": 2, "news_type": 1, "page_size": 20},
                )
                for index in range(4)
            ],
        ]
        with (
            patch.dict(os.environ, {"MOEGAL_RSS_FETCH_CONCURRENCY": "8"}),
            patch(
                "services.rss_pipeline.sources._invoke_collector",
                side_effect=fake_collect,
            ),
        ):
            result = collect_content_sources(sources)

        self.assertEqual(result.successful_source_count, 8)
        self.assertEqual(maximum, {"bilibili": 2, "mihoyo": 2})


if __name__ == "__main__":
    unittest.main()
