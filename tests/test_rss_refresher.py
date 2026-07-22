import os
import tempfile
import threading
import time
import unittest
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, select

from db.models import ContentItem
from services.rss_pipeline.refresher import (
    DEFAULT_RSS_REFRESH_INTERVAL_SECONDS,
    MIN_RSS_REFRESH_INTERVAL_SECONDS,
    RSS_REFRESH_INTERVAL_ENV,
    RssCacheRefreshResult,
    get_rss_refresh_interval_seconds,
    refresh_rss_cache_once,
    start_rss_cache_refresher,
)
from services.rss_pipeline.feeds import RssEntry, RssFetchError, RssFetchResult


class RssCacheRefresherTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)

        self.stack = ExitStack()
        self.stack.enter_context(
            patch("services.rss_pipeline.content_store.get_engine", return_value=self.engine)
        )

    def tearDown(self) -> None:
        self.stack.close()

    def test_refresh_once_upserts_successful_entries_and_reports_errors(self) -> None:
        entry = _rss_entry(title="ブルアカ 新活动公开", entry_id="entry-1")
        fetch_result = RssFetchResult(
            entries=[entry],
            errors=[RssFetchError(feed_url="https://example.com/broken.xml", message="timeout")],
        )

        with (
            patch(
                "services.rss_pipeline.refresher.get_configured_feed_urls",
                return_value=["https://example.com/feed.xml", "https://example.com/broken.xml"],
            ),
            patch("services.rss_pipeline.refresher.fetch_rss_entries", return_value=fetch_result),
        ):
            result = refresh_rss_cache_once()

        self.assertEqual(result.feed_count, 2)
        self.assertEqual(result.entry_count, 1)
        self.assertEqual(result.error_count, 1)
        self.assertEqual(result.created_count, 1)
        self.assertEqual(result.updated_count, 0)
        with Session(self.engine) as session:
            item = session.exec(select(ContentItem)).one()
        self.assertEqual(item.title, "ブルアカ 新活动公开")

    def test_refresh_once_skips_when_no_sources_are_configured(self) -> None:
        with (
            patch("services.rss_pipeline.refresher.get_configured_feed_urls", return_value=[]),
            patch("services.rss_pipeline.refresher.fetch_rss_entries") as fetch_mock,
        ):
            result = refresh_rss_cache_once()

        fetch_mock.assert_not_called()
        self.assertEqual(result, RssCacheRefreshResult(feed_count=0, entry_count=0, error_count=0))
        with Session(self.engine) as session:
            self.assertEqual(len(session.exec(select(ContentItem)).all()), 0)

    def test_refresh_keeps_cached_content_when_embedding_fails(self) -> None:
        entry = _rss_entry(title="蓝色档案 新活动", entry_id="entry-index-error")
        fetch_result = RssFetchResult(entries=[entry], errors=[])

        with (
            patch(
                "services.rss_pipeline.refresher.get_configured_feed_urls",
                return_value=["https://example.com/feed.xml"],
            ),
            patch(
                "services.rss_pipeline.refresher.fetch_rss_entries",
                return_value=fetch_result,
            ),
            patch(
                "services.rss_pipeline.refresher.index_content_items",
                side_effect=RuntimeError("embedding unavailable"),
            ),
            patch("services.rss_pipeline.refresher.logger.exception"),
        ):
            result = refresh_rss_cache_once()

        self.assertEqual(result.created_count, 1)
        self.assertEqual(result.index_error_count, 1)
        with Session(self.engine) as session:
            self.assertEqual(len(session.exec(select(ContentItem)).all()), 1)

    def test_refresh_interval_defaults_and_validation(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                get_rss_refresh_interval_seconds(),
                DEFAULT_RSS_REFRESH_INTERVAL_SECONDS,
            )

        with patch.dict(os.environ, {RSS_REFRESH_INTERVAL_ENV: "not-an-int"}, clear=True):
            self.assertEqual(
                get_rss_refresh_interval_seconds(),
                DEFAULT_RSS_REFRESH_INTERVAL_SECONDS,
            )

        with patch.dict(os.environ, {RSS_REFRESH_INTERVAL_ENV: "12"}, clear=True):
            self.assertEqual(
                get_rss_refresh_interval_seconds(),
                MIN_RSS_REFRESH_INTERVAL_SECONDS,
            )

        valid_interval = MIN_RSS_REFRESH_INTERVAL_SECONDS + 60
        with patch.dict(os.environ, {RSS_REFRESH_INTERVAL_ENV: str(valid_interval)}, clear=True):
            self.assertEqual(get_rss_refresh_interval_seconds(), valid_interval)

    def test_refresher_runs_when_timestamp_file_is_missing_and_stops(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            timestamp_path = Path(temp_dir) / "rss_last_refresh_at"
            ran = threading.Event()

            def fake_refresh() -> RssCacheRefreshResult:
                ran.set()
                return RssCacheRefreshResult(feed_count=1, entry_count=0, error_count=0)

            with (
                patch("services.rss_pipeline.refresher.RSS_LAST_REFRESH_AT_PATH", timestamp_path),
                patch(
                    "services.rss_pipeline.refresher.refresh_rss_cache_once",
                    side_effect=fake_refresh,
                ),
            ):
                refresher = start_rss_cache_refresher(interval_seconds=60)
                try:
                    self.assertTrue(ran.wait(timeout=1.0))
                finally:
                    refresher.stop(timeout=1.0)

            self.assertFalse(refresher.thread.is_alive())
            self.assertTrue(timestamp_path.exists())

    def test_refresher_waits_when_timestamp_is_recent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            timestamp_path = Path(temp_dir) / "rss_last_refresh_at"
            timestamp_path.write_text(f"{time.time()}\n", encoding="utf-8")
            ran = threading.Event()

            def fake_refresh() -> RssCacheRefreshResult:
                ran.set()
                return RssCacheRefreshResult(feed_count=1, entry_count=0, error_count=0)

            with (
                patch("services.rss_pipeline.refresher.RSS_LAST_REFRESH_AT_PATH", timestamp_path),
                patch(
                    "services.rss_pipeline.refresher.refresh_rss_cache_once",
                    side_effect=fake_refresh,
                ),
            ):
                refresher = start_rss_cache_refresher(interval_seconds=60)
                try:
                    self.assertFalse(ran.wait(timeout=0.2))
                finally:
                    refresher.stop(timeout=1.0)

            self.assertFalse(refresher.thread.is_alive())

    def test_refresher_runs_when_timestamp_is_expired_and_updates_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            timestamp_path = Path(temp_dir) / "rss_last_refresh_at"
            previous_timestamp = time.time() - 120
            timestamp_path.write_text(f"{previous_timestamp}\n", encoding="utf-8")
            ran = threading.Event()

            def fake_refresh() -> RssCacheRefreshResult:
                ran.set()
                return RssCacheRefreshResult(feed_count=1, entry_count=0, error_count=0)

            with (
                patch("services.rss_pipeline.refresher.RSS_LAST_REFRESH_AT_PATH", timestamp_path),
                patch(
                    "services.rss_pipeline.refresher.refresh_rss_cache_once",
                    side_effect=fake_refresh,
                ),
            ):
                refresher = start_rss_cache_refresher(interval_seconds=60)
                try:
                    self.assertTrue(ran.wait(timeout=1.0))
                finally:
                    refresher.stop(timeout=1.0)

            self.assertFalse(refresher.thread.is_alive())
            self.assertGreater(
                float(timestamp_path.read_text(encoding="utf-8")),
                previous_timestamp,
            )

    def test_refresher_runs_when_timestamp_file_is_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            timestamp_path = Path(temp_dir) / "rss_last_refresh_at"
            timestamp_path.write_text("not-a-timestamp\n", encoding="utf-8")
            ran = threading.Event()

            def fake_refresh() -> RssCacheRefreshResult:
                ran.set()
                return RssCacheRefreshResult(feed_count=1, entry_count=0, error_count=0)

            with (
                patch("services.rss_pipeline.refresher.RSS_LAST_REFRESH_AT_PATH", timestamp_path),
                patch(
                    "services.rss_pipeline.refresher.refresh_rss_cache_once",
                    side_effect=fake_refresh,
                ),
            ):
                refresher = start_rss_cache_refresher(interval_seconds=60)
                try:
                    self.assertTrue(ran.wait(timeout=1.0))
                finally:
                    refresher.stop(timeout=1.0)

            self.assertFalse(refresher.thread.is_alive())

    def test_refresher_does_not_update_timestamp_when_refresh_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            timestamp_path = Path(temp_dir) / "rss_last_refresh_at"
            ran = threading.Event()

            def fake_refresh() -> RssCacheRefreshResult:
                ran.set()
                raise RuntimeError("boom")

            with (
                patch("services.rss_pipeline.refresher.RSS_LAST_REFRESH_AT_PATH", timestamp_path),
                patch(
                    "services.rss_pipeline.refresher.refresh_rss_cache_once",
                    side_effect=fake_refresh,
                ),
            ):
                refresher = start_rss_cache_refresher(interval_seconds=60)
                try:
                    self.assertTrue(ran.wait(timeout=1.0))
                finally:
                    refresher.stop(timeout=1.0)

            self.assertFalse(refresher.thread.is_alive())
            self.assertFalse(timestamp_path.exists())


def _rss_entry(*, title: str, entry_id: str) -> RssEntry:
    return RssEntry(
        feed_url="https://example.com/feed.xml",
        feed_title="Example Feed",
        entry_id=entry_id,
        link=f"https://example.com/{entry_id}",
        title=title,
        summary="摘要",
        author="Example Author",
        published_at=datetime.now(timezone.utc),
        raw={
            "feed_url": "https://example.com/feed.xml",
            "feed_title": "Example Feed",
            "entry_id": entry_id,
            "link": f"https://example.com/{entry_id}",
        },
    )


if __name__ == "__main__":
    unittest.main()
