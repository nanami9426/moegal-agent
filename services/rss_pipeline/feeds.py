from __future__ import annotations

import calendar
import html
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import feedparser
import httpx

if TYPE_CHECKING:
    from services.rss_pipeline.sources import ContentSource


_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class RssEntry:
    """所有内容源写入缓存前使用的统一条目结构。"""

    feed_url: str
    feed_title: str | None
    entry_id: str | None
    link: str | None
    title: str | None
    summary: str | None
    author: str | None
    published_at: datetime | None
    raw: dict[str, Any]


def collect(source: ContentSource, client: httpx.Client) -> list[RssEntry]:
    """抓取一个原生 RSS/Atom 内容源。"""

    feed_url = str(source.options["url"])
    response = client.get(feed_url)
    response.raise_for_status()

    parsed = feedparser.parse(response.content)
    if parsed.bozo and not parsed.entries:
        error = getattr(parsed, "bozo_exception", "invalid feed")
        raise ValueError(f"无法解析 RSS/Atom: {error}")

    feed_title = _clean_text(parsed.feed.get("title"))
    return [
        _normalize_entry(source, feed_url, feed_title, entry)
        for entry in parsed.entries
    ]


def _normalize_entry(
    source: ContentSource,
    feed_url: str,
    feed_title: str | None,
    entry: Any,
) -> RssEntry:
    upstream_entry_id = _clean_text(entry.get("id") or entry.get("guid"))
    link = _clean_text(entry.get("link"))
    title = _clean_text(entry.get("title"))
    summary = _extract_summary(entry)
    author = _clean_text(entry.get("author") or entry.get("creator"))
    published_at = _extract_published_at(entry)
    published_text = _clean_text(
        entry.get("published") or entry.get("updated") or entry.get("created")
    )

    # 一些 Feed 使用简单数字作 GUID；加来源命名空间可避免不同 Feed 互相覆盖。
    identity = upstream_entry_id or link
    entry_id = f"feed:{source.id}:{identity}" if identity else None
    raw = {
        "source_key": source.id,
        "source_kind": source.kind,
        "request_url": feed_url,
        "feed_title": feed_title,
        "upstream_entry_id": upstream_entry_id,
        "link": link,
        "published": published_text,
        "tags": _extract_tags(entry),
    }

    return RssEntry(
        feed_url=feed_url,
        feed_title=feed_title,
        entry_id=entry_id,
        link=link,
        title=title,
        summary=summary,
        author=author,
        published_at=published_at,
        raw=raw,
    )


def _extract_summary(entry: Any) -> str | None:
    summary = entry.get("summary") or entry.get("description")
    if summary:
        return _clean_text(summary)

    content = entry.get("content")
    if isinstance(content, list) and content:
        first = content[0]
        if isinstance(first, dict):
            return _clean_text(first.get("value"))

    return None


def _extract_published_at(entry: Any) -> datetime | None:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        parsed = entry.get(key)
        if parsed:
            return datetime.fromtimestamp(calendar.timegm(parsed), timezone.utc)

    return None


def _extract_tags(entry: Any) -> list[str]:
    tags = entry.get("tags")
    if not isinstance(tags, list):
        return []

    result: list[str] = []
    for tag in tags:
        if isinstance(tag, dict):
            term = _clean_text(tag.get("term"))
            if term:
                result.append(term)
    return result


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None

    text = html.unescape(str(value))
    text = _HTML_TAG_RE.sub(" ", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text or None
