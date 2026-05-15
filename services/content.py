import hashlib
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from db.models import ContentItem, utc_now
from db.session import get_engine
from services.rss import RssEntry


@dataclass(frozen=True)
class ContentUpsertResult:
    items: list[ContentItem]
    created_count: int
    updated_count: int


def upsert_rss_entries(entries: list[RssEntry]) -> ContentUpsertResult:
    if not entries:
        return ContentUpsertResult(items=[], created_count=0, updated_count=0)

    deduped_entries = _dedupe_entries(entries)
    items: list[ContentItem] = []
    created_count = 0
    updated_count = 0

    with Session(get_engine()) as session:
        for source_id, entry in deduped_entries.items():
            content_hash = _content_hash(entry)
            item = session.exec(
                select(ContentItem).where(
                    ContentItem.source_type == "rss",
                    ContentItem.source_id == source_id,
                )
            ).first()

            if item is None:
                item = ContentItem(
                    source_type="rss",
                    source_id=source_id,
                    source_url=entry.link or entry.feed_url,
                    title=entry.title,
                    summary=entry.summary,
                    author=entry.author or entry.feed_title,
                    published_at=entry.published_at,
                    fetched_at=utc_now(),
                    raw=entry.raw,
                    hash=content_hash, # 内容 hash，用于后续判断内容是否变化
                )
                session.add(item)
                created_count += 1
            else:
                item.source_url = entry.link or entry.feed_url
                item.title = entry.title
                item.summary = entry.summary
                item.author = entry.author or entry.feed_title
                item.published_at = entry.published_at
                item.fetched_at = utc_now()
                item.raw = entry.raw
                item.hash = content_hash
                session.add(item)
                updated_count += 1

            items.append(item)

        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            items = _load_existing_items(session, deduped_entries.keys())
            return ContentUpsertResult(
                items=items,
                created_count=0,
                updated_count=len(items),
            )

        for item in items:
            session.refresh(item)

    return ContentUpsertResult(
        items=items,
        created_count=created_count,
        updated_count=updated_count,
    )


def _dedupe_entries(entries: list[RssEntry]) -> dict[str, RssEntry]:
    result: dict[str, RssEntry] = {}
    for entry in entries:
        source_id = rss_source_id(entry)
        if source_id not in result:
            result[source_id] = entry
    return result


def _load_existing_items(session: Session, source_ids) -> list[ContentItem]:
    return list(
        session.exec(
            select(ContentItem).where(
                ContentItem.source_type == "rss",
                ContentItem.source_id.in_(list(source_ids)),
            )
        ).all()
    )


def rss_source_id(entry: RssEntry) -> str:
    # 给一个 RSS entry 生成数据库层面的唯一 ID，存进 ContentItem.source_id
    candidate = (entry.entry_id or entry.link or "").strip()
    if candidate:
        if len(candidate) <= 255:
            return candidate
        # 如果太长，超过数据库字段长度，就 hash 成固定长度
        return hashlib.sha256(candidate.encode("utf-8")).hexdigest()
    # 如果既没有 entry_id 也没有 link，就只能退化用这些字段拼一个指纹
    fallback = "|".join(
        [
            entry.feed_url,
            entry.title or "",
            entry.published_at.isoformat() if entry.published_at else "",
        ]
    )
    return hashlib.sha256(fallback.encode("utf-8")).hexdigest()


def _content_hash(entry: RssEntry) -> str:
    value = "|".join(
        [
            entry.feed_url,
            entry.entry_id or "",
            entry.link or "",
            entry.title or "",
            entry.summary or "",
            entry.author or "",
            entry.published_at.isoformat() if entry.published_at else "",
        ]
    )
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
