import unittest
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, select

from db.models import ContentItem, Delivery, Subscription, User
from services.account.subscriptions import create_subscription, delete_subscription, list_subscriptions
from services.rss_pipeline.content_store import upsert_rss_entries
from services.rss_pipeline.digest import mark_deliveries_sent, prepare_daily_digest
from services.rss_pipeline.feeds import RssEntry


_DEFAULT_PUBLISHED_AT = object()


class DigestServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)
        self.user_id = 1_000_000_001
        with Session(self.engine) as session:
            session.add(
                User(
                    id=self.user_id,
                    platform="tg",
                    platform_user_id="42",
                    username="tester",
                )
            )
            session.commit()

        self.stack = ExitStack()
        self.stack.enter_context(patch("services.account.subscriptions.get_engine", return_value=self.engine))
        self.stack.enter_context(patch("services.rss_pipeline.content_store.get_engine", return_value=self.engine))
        self.stack.enter_context(patch("services.rss_pipeline.digest.get_engine", return_value=self.engine))
        self.sources_mock = self.stack.enter_context(
            patch(
                "services.rss_pipeline.digest.load_content_sources",
                return_value=[SimpleNamespace(id="example-feed")],
            )
        )

    def tearDown(self) -> None:
        self.stack.close()

    def test_create_subscription_dedupes_and_reenables(self) -> None:
        first = create_subscription(user_id=self.user_id, target="ブルアカ")
        second = create_subscription(user_id=self.user_id, target="ブルアカ")

        self.assertTrue(first.created)
        self.assertFalse(second.created)
        self.assertFalse(second.reenabled)

        with Session(self.engine) as session:
            subscription = session.exec(select(Subscription)).one()
            subscription.enabled = False
            session.add(subscription)
            session.commit()

        third = create_subscription(user_id=self.user_id, target="ブルアカ")
        self.assertFalse(third.created)
        self.assertTrue(third.reenabled)

        with Session(self.engine) as session:
            self.assertEqual(len(session.exec(select(Subscription)).all()), 1)

    def test_delete_subscription_disables_and_allows_reenable(self) -> None:
        create_subscription(user_id=self.user_id, target="ブルアカ")

        result = delete_subscription(user_id=self.user_id, target="ブルアカ")

        self.assertTrue(result.deleted)
        self.assertIsNotNone(result.subscription)
        self.assertEqual(list_subscriptions(self.user_id), [])

        with Session(self.engine) as session:
            subscription = session.exec(select(Subscription)).one()
            self.assertFalse(subscription.enabled)

        reenabled = create_subscription(user_id=self.user_id, target="ブルアカ")

        self.assertFalse(reenabled.created)
        self.assertTrue(reenabled.reenabled)
        with Session(self.engine) as session:
            subscriptions = session.exec(select(Subscription)).all()
            self.assertEqual(len(subscriptions), 1)
            self.assertTrue(subscriptions[0].enabled)

    def test_delete_subscription_missing_or_disabled_is_noop(self) -> None:
        missing = delete_subscription(user_id=self.user_id, target="ブルアカ")

        self.assertFalse(missing.deleted)
        self.assertIsNone(missing.subscription)

        create_subscription(user_id=self.user_id, target="ブルアカ")
        first = delete_subscription(user_id=self.user_id, target="ブルアカ")
        second = delete_subscription(user_id=self.user_id, target="ブルアカ")

        self.assertTrue(first.deleted)
        self.assertFalse(second.deleted)
        self.assertIsNotNone(second.subscription)

    def test_upsert_rss_entries_dedupes_content_items(self) -> None:
        entry = self._rss_entry(title="ブルアカ 新イベント", entry_id="entry-1")

        first = upsert_rss_entries([entry])
        second = upsert_rss_entries([entry])

        self.assertEqual(first.created_count, 1)
        self.assertEqual(second.created_count, 0)
        with Session(self.engine) as session:
            self.assertEqual(len(session.exec(select(ContentItem)).all()), 1)

    def test_upsert_dedupes_same_canonical_item_across_sources(self) -> None:
        canonical_url = "https://www.bilibili.com/video/BV1example"
        weekly = self._rss_entry(
            title="每周必看视频",
            entry_id=canonical_url,
            link=canonical_url,
            source_key="bilibili-weekly",
        )
        ranking = self._rss_entry(
            title="分区榜视频",
            entry_id=canonical_url,
            link=canonical_url,
            source_key="bilibili-anime-rank",
        )

        result = upsert_rss_entries([weekly, ranking])

        self.assertEqual(result.created_count, 1)
        with Session(self.engine) as session:
            self.assertEqual(len(session.exec(select(ContentItem)).all()), 1)

    def test_upsert_rss_entries_truncates_long_database_fields(self) -> None:
        entry = self._rss_entry(
            title="T" * 600,
            entry_id="entry-long-fields",
            link="https://example.com/" + ("x" * 2100),
            author="A" * 300,
        )

        upsert_rss_entries([entry])

        with Session(self.engine) as session:
            item = session.exec(select(ContentItem)).one()

        self.assertEqual(len(item.title), 512)
        self.assertEqual(len(item.author), 255)
        self.assertEqual(len(item.source_url), 2048)
        self.assertLessEqual(len(item.source_id), 255)

    def test_digest_matches_keyword_marks_sent_and_does_not_repeat(self) -> None:
        create_subscription(user_id=self.user_id, target="ブルアカ")
        upsert_rss_entries(
            [
                self._rss_entry(
                    title="ブルアカ 新活动公开",
                    summary="今天公开了新的活动情报。",
                    entry_id="entry-1",
                )
            ]
        )

        with (
            patch(
                "services.rss_pipeline.sources.collect_content_sources",
            ) as collect_mock,
        ):
            first = prepare_daily_digest(self.user_id)

        collect_mock.assert_not_called()
        self.assertIn("ブルアカ 新活动公开", first.text)
        self.assertEqual(first.item_count, 1)
        self.assertEqual(len(first.delivery_ids), 1)

        mark_deliveries_sent(first.delivery_ids)
        with Session(self.engine) as session:
            delivery = session.exec(select(Delivery)).one()
            self.assertEqual(delivery.status, "sent")
            self.assertIsNotNone(delivery.sent_at)

        second = prepare_daily_digest(self.user_id)

        self.assertIn("暂无新的订阅内容", second.text)
        with Session(self.engine) as session:
            self.assertEqual(len(session.exec(select(Delivery)).all()), 1)

    def test_deleting_subscription_cancels_existing_pending_digest_items(self) -> None:
        create_subscription(user_id=self.user_id, target="ブルアカ")
        create_subscription(user_id=self.user_id, target="原神")
        upsert_rss_entries(
            [
                self._rss_entry(
                    title="ブルアカ 新活动公开",
                    summary="今天公开了新的活动情报。",
                    entry_id="entry-1",
                )
            ]
        )

        first = prepare_daily_digest(self.user_id)
        self.assertIn("ブルアカ 新活动公开", first.text)
        self.assertEqual(len(first.delivery_ids), 1)

        delete_subscription(user_id=self.user_id, target="ブルアカ")
        second = prepare_daily_digest(self.user_id)

        self.assertNotIn("ブルアカ 新活动公开", second.text)
        self.assertIn("暂无新的订阅内容", second.text)
        with Session(self.engine) as session:
            delivery = session.exec(select(Delivery)).one()
            self.assertEqual(delivery.status, "canceled")

    def test_digest_filters_pending_items_for_disabled_subscriptions(self) -> None:
        disabled = create_subscription(user_id=self.user_id, target="ブルアカ").subscription
        create_subscription(user_id=self.user_id, target="原神")
        upsert_rss_entries(
            [
                self._rss_entry(
                    title="ブルアカ 新活动公开",
                    summary="今天公开了新的活动情报。",
                    entry_id="entry-1",
                )
            ]
        )

        with Session(self.engine) as session:
            subscription = session.get(Subscription, disabled.id)
            self.assertIsNotNone(subscription)
            subscription.enabled = False
            session.add(subscription)
            content_item = session.exec(select(ContentItem)).one()
            session.add(
                Delivery(
                    user_id=self.user_id,
                    subscription_id=disabled.id,
                    content_item_id=content_item.id,
                    status="pending",
                )
            )
            session.commit()

        result = prepare_daily_digest(self.user_id)

        self.assertNotIn("ブルアカ 新活动公开", result.text)
        self.assertIn("暂无新的订阅内容", result.text)

    def test_digest_ignores_non_matching_content(self) -> None:
        create_subscription(user_id=self.user_id, target="ブルアカ")
        upsert_rss_entries([self._rss_entry(title="孤独摇滚 新情报", entry_id="entry-2")])

        result = prepare_daily_digest(self.user_id)

        self.assertIn("暂无新的订阅内容", result.text)
        with Session(self.engine) as session:
            self.assertEqual(len(session.exec(select(Delivery)).all()), 0)

    def test_digest_accepts_entry_without_link_or_published_time(self) -> None:
        create_subscription(user_id=self.user_id, target="ブルアカ")
        upsert_rss_entries(
            [
                self._rss_entry(
                    title="ブルアカ 无链接条目",
                    entry_id=None,
                    link=None,
                    published_at=None,
                )
            ],
        )

        result = prepare_daily_digest(self.user_id)

        self.assertIn("ブルアカ 无链接条目", result.text)
        self.assertEqual(len(result.delivery_ids), 1)

        with Session(self.engine) as session:
            item = session.exec(select(ContentItem)).one()
            self.assertEqual(item.source_url, "https://example.com/feed.xml")
            self.assertIsNone(item.published_at)

    def test_digest_handles_missing_source_subscription_and_empty_cache(self) -> None:
        self.sources_mock.return_value = []
        no_source = prepare_daily_digest(self.user_id)
        self.assertIn("还没有配置内容源", no_source.text)

        self.sources_mock.return_value = [SimpleNamespace(id="example-feed")]
        no_subscription = prepare_daily_digest(self.user_id)
        self.assertIn("你还没有订阅", no_subscription.text)

        create_subscription(user_id=self.user_id, target="ブルアカ")
        refreshing = prepare_daily_digest(self.user_id)

        self.assertIn("内容缓存还在后台刷新", refreshing.text)

    def test_digest_ignores_content_without_active_source_marker(self) -> None:
        create_subscription(user_id=self.user_id, target="ブルアカ")
        upsert_rss_entries(
            [self._rss_entry(title="孤独摇滚 新情报", entry_id="active-item")]
        )
        with Session(self.engine) as session:
            session.add(
                ContentItem(
                    source_type="rss",
                    source_id="legacy-rsshub-item",
                    source_url="https://legacy.example/item",
                    title="ブルアカ 旧 RSSHub 内容",
                    fetched_at=datetime.now(timezone.utc),
                    raw={},
                )
            )
            session.commit()

        result = prepare_daily_digest(self.user_id)

        self.assertIn("暂无新的订阅内容", result.text)
        with Session(self.engine) as session:
            self.assertEqual(len(session.exec(select(Delivery)).all()), 0)

    def test_digest_expires_undated_content_and_existing_pending_delivery(self) -> None:
        subscription = create_subscription(
            user_id=self.user_id,
            target="ブルアカ",
        ).subscription
        upsert_rss_entries(
            [
                self._rss_entry(title="ブルアカ 旧内容", entry_id="stale", published_at=None),
                self._rss_entry(title="孤独摇滚 新情报", entry_id="fresh"),
            ]
        )
        with Session(self.engine) as session:
            stale = session.exec(
                select(ContentItem).where(ContentItem.source_id == "stale")
            ).one()
            stale.fetched_at = datetime.now(timezone.utc) - timedelta(days=3)
            session.add(stale)
            session.add(
                Delivery(
                    user_id=self.user_id,
                    subscription_id=subscription.id,
                    content_item_id=stale.id,
                    status="pending",
                )
            )
            session.commit()

        result = prepare_daily_digest(self.user_id)

        self.assertNotIn("ブルアカ 旧内容", result.text)
        self.assertIn("暂无新的订阅内容", result.text)

    def test_digest_uses_published_time_before_recent_fetch_time(self) -> None:
        create_subscription(user_id=self.user_id, target="ブルアカ")
        upsert_rss_entries(
            [
                self._rss_entry(
                    title="ブルアカ 三天前情报",
                    entry_id="old-published",
                    published_at=datetime.now(timezone.utc) - timedelta(days=3),
                ),
                self._rss_entry(title="孤独摇滚 新情报", entry_id="fresh"),
            ]
        )

        result = prepare_daily_digest(self.user_id)

        self.assertNotIn("ブルアカ 三天前情报", result.text)
        self.assertIn("暂无新的订阅内容", result.text)

    def _rss_entry(
        self,
        *,
        title: str,
        entry_id: str | None,
        summary: str = "摘要",
        author: str | None = "Example Author",
        link: str | None = "https://example.com/default",
        published_at: datetime | None | object = _DEFAULT_PUBLISHED_AT,
        source_key: str = "example-feed",
    ) -> RssEntry:
        entry_link = link
        if link == "https://example.com/default" and entry_id is not None:
            entry_link = f"https://example.com/{entry_id}"

        entry_published_at = (
            datetime.now(timezone.utc)
            if published_at is _DEFAULT_PUBLISHED_AT
            else published_at
        )

        return RssEntry(
            feed_url="https://example.com/feed.xml",
            feed_title="Example Feed",
            entry_id=entry_id,
            link=entry_link,
            title=title,
            summary=summary,
            author=author,
            published_at=entry_published_at,
            raw={
                "source_key": source_key,
                "source_kind": "feed",
                "request_url": "https://example.com/feed.xml",
                "feed_url": "https://example.com/feed.xml",
                "feed_title": "Example Feed",
                "entry_id": entry_id,
                "link": entry_link,
            },
        )


if __name__ == "__main__":
    unittest.main()
