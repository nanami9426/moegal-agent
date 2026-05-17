from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from db.models import ContentItem, Delivery, Subscription, utc_now
from db.session import get_engine
from services.rss_pipeline.feeds import get_configured_feed_urls


DIGEST_LOOKBACK_HOURS = 48
DIGEST_MAX_ITEMS = 5


@dataclass(frozen=True)
class DigestResult:
    text: str
    delivery_ids: tuple[int, ...]
    item_count: int = 0


def prepare_daily_digest(user_id: int) -> DigestResult:
    feed_urls = get_configured_feed_urls()
    if not feed_urls:
        return DigestResult(
            text="还没有配置内容源。请先在 config/rss_feeds.txt 添加 RSSHub route。",
            delivery_ids=(),
        )

    subscriptions = _list_active_keyword_subscriptions(user_id)
    if not subscriptions:
        return DigestResult(
            text="你还没有订阅。可以先用 /subscribe 关键词 添加订阅。",
            delivery_ids=(),
        )

    if not _has_cached_rss_content():
        return DigestResult(text="内容缓存还在后台刷新，请稍后再试。", delivery_ids=())

    # 按订阅匹配内容，生成待投递记录
    _create_pending_deliveries(user_id, subscriptions)
    digest_items = _list_pending_digest_items(user_id, DIGEST_MAX_ITEMS)

    if not digest_items:
        return DigestResult(text="暂无新的订阅内容。", delivery_ids=())

    text = _format_digest(digest_items)
    delivery_ids = tuple(item.delivery_id for item in digest_items)
    return DigestResult(text=text, delivery_ids=delivery_ids, item_count=len(digest_items))


def build_daily_digest(user_id: int) -> str:
    result = prepare_daily_digest(user_id)
    mark_deliveries_sent(result.delivery_ids)
    return result.text


def mark_deliveries_sent(delivery_ids: Iterable[int]) -> None:
    ids = list(delivery_ids)
    if not ids:
        return

    with Session(get_engine()) as session:
        deliveries = session.exec(
            select(Delivery).where(Delivery.id.in_(ids))
        ).all()
        now = utc_now()
        for delivery in deliveries:
            delivery.status = "sent"
            delivery.sent_at = now
            delivery.error_message = None
            session.add(delivery)
        session.commit()


def _list_active_keyword_subscriptions(user_id: int) -> list[Subscription]:
    with Session(get_engine()) as session:
        return list(
            session.exec(
                select(Subscription)
                .where(
                    Subscription.user_id == user_id,
                    Subscription.enabled == True,  # noqa: E712
                    Subscription.type == "keyword",
                )
                .order_by(Subscription.created_at)
            ).all()
        )


def _has_cached_rss_content() -> bool:
    with Session(get_engine()) as session:
        return (
            session.exec(
                select(ContentItem.id)
                .where(ContentItem.source_type == "rss")
                .limit(1)
            ).first()
            is not None
        )


def _create_pending_deliveries(
    user_id: int,
    subscriptions: list[Subscription],
) -> int:
    cutoff = utc_now() - timedelta(hours=DIGEST_LOOKBACK_HOURS)
    created_count = 0

    with Session(get_engine()) as session:
        items = session.exec(
            select(ContentItem).where(
                ContentItem.source_type == "rss",
                or_(
                    ContentItem.published_at.is_(None),
                    ContentItem.published_at >= cutoff,
                ),
            )
        ).all()

        content_item_ids = [
            item.id
            for item in items
            if item.id is not None
        ]
        if not content_item_ids:
            return 0

        existing_content_item_ids = set(
            session.exec(
                select(Delivery.content_item_id).where(
                    Delivery.user_id == user_id,
                    Delivery.content_item_id.in_(content_item_ids),
                )
            ).all()
        )

        for item in items:
            if item.id is None:
                continue

            matched_subscription = _match_subscription(item, subscriptions)
            if matched_subscription is None:
                continue

            if item.id in existing_content_item_ids:
                continue

            delivery = Delivery(
                user_id=user_id,
                subscription_id=matched_subscription.id,
                content_item_id=item.id,
                status="pending",
            )
            session.add(delivery)
            created_count += 1
            existing_content_item_ids.add(item.id)

        try:
            session.commit()
        except IntegrityError:
            session.rollback()

    return created_count


@dataclass(frozen=True)
class _DigestItem:
    delivery_id: int
    title: str | None
    summary: str | None
    author: str | None
    source_url: str | None
    published_at: datetime | None
    created_at: datetime


def _list_pending_digest_items(user_id: int, limit: int) -> list[_DigestItem]:
    with Session(get_engine()) as session:
        rows = session.exec(
            select(Delivery, ContentItem)
            .join(ContentItem, Delivery.content_item_id == ContentItem.id)
            .where(
                Delivery.user_id == user_id,
                Delivery.status == "pending",
            )
        ).all()

    items = [
        _DigestItem(
            delivery_id=delivery.id,
            title=content.title,
            summary=content.summary,
            author=content.author,
            source_url=content.source_url,
            published_at=content.published_at,
            created_at=delivery.created_at,
        )
        for delivery, content in rows
        if delivery.id is not None
    ]
    items.sort(key=_digest_sort_key, reverse=True)
    return items[:limit]


def _match_subscription(
    item: ContentItem,
    subscriptions: list[Subscription],
) -> Subscription | None:
    haystack = " ".join(
        value
        for value in [item.title, item.summary, item.author]
        if value
    ).casefold()

    if not haystack:
        return None

    for subscription in subscriptions:
        target = subscription.target.strip().casefold()
        if target and target in haystack:
            return subscription

    return None


def _format_digest(items: list[_DigestItem]) -> str:
    lines = [f"今日摘要：找到 {len(items)} 条新的订阅内容。"]

    for index, item in enumerate(items, start=1):
        lines.append("")
        lines.append(f"{index}. {item.title or '无标题'}")
        meta = _format_meta(item)
        if meta:
            lines.append(f"来源：{meta}")
        if item.summary:
            lines.append(f"摘要：{_truncate(item.summary, 140)}")
        if item.source_url:
            lines.append(f"链接：{item.source_url}")

    return "\n".join(lines)


def _format_meta(item: _DigestItem) -> str:
    parts: list[str] = []
    if item.author:
        parts.append(item.author)
    if item.published_at:
        parts.append(item.published_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))
    return " / ".join(parts)


def _truncate(value: str, max_length: int) -> str:
    text = " ".join(value.split())
    if len(text) <= max_length:
        return text
    return text[: max_length - 1].rstrip() + "…"


def _digest_sort_key(item: _DigestItem) -> tuple[bool, datetime, datetime]:
    fallback = datetime.min.replace(tzinfo=timezone.utc)
    published_at = item.published_at or fallback
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    return (item.published_at is not None, published_at, item.created_at)
