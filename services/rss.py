import calendar
import html
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import feedparser
import httpx


_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class RssEntry:
    feed_url: str
    feed_title: str | None
    entry_id: str | None
    link: str | None
    title: str | None
    summary: str | None
    author: str | None
    published_at: datetime | None
    raw: dict[str, Any]


@dataclass(frozen=True)
class RssFetchError:
    feed_url: str
    message: str


@dataclass(frozen=True)
class RssFetchResult:
    entries: list[RssEntry]
    errors: list[RssFetchError]


def get_configured_feed_urls() -> list[str]:
    raw_value = os.getenv("MOEGAL_RSS_FEEDS", "")
    return [
        part.strip()
        for part in re.split(r"[,\n]", raw_value)
        if part.strip()
    ]


def fetch_rss_entries(feed_urls: list[str] | None = None) -> RssFetchResult:
    # 从一组 RSS/RSSHub URL 抓取内容，解析成统一的 RssEntry 列表
    # 同时把失败的源记录到 errors，最后一起返回。
    urls = feed_urls if feed_urls is not None else get_configured_feed_urls()
    entries: list[RssEntry] = [] # 成功解析出来的 RSS 条目
    errors: list[RssFetchError] = [] # 抓取失败或解析失败的 feed

    if not urls:
        return RssFetchResult(entries=entries, errors=errors)

    with httpx.Client(follow_redirects=True, timeout=15.0) as client:
        for feed_url in urls:
            try:
                response = client.get(feed_url)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                errors.append(RssFetchError(feed_url=feed_url, message=str(exc)))
                continue
            # 用 feedparser 解析 RSS/Atom 内容
            parsed = feedparser.parse(response.content)
            if parsed.bozo and not parsed.entries:
                # feedparser 的 bozo 表示这个 feed 有解析异常
                # 如果解析失败且没有条目，就记录错误，然后跳过
                errors.append(
                    RssFetchError(
                        feed_url=feed_url,
                        message=str(getattr(parsed, "bozo_exception", "invalid feed")),
                    )
                )
                continue

            feed_title = _clean_text(parsed.feed.get("title"))
            for entry in parsed.entries:
                entries.append(_normalize_entry(feed_url, feed_title, entry))

    return RssFetchResult(entries=entries, errors=errors)


def _normalize_entry(feed_url: str, feed_title: str | None, entry: Any) -> RssEntry:
    entry_id = _clean_text(entry.get("id") or entry.get("guid"))
    link = _clean_text(entry.get("link"))
    title = _clean_text(entry.get("title"))
    summary = _extract_summary(entry)
    author = _clean_text(entry.get("author") or entry.get("creator"))
    published_at = _extract_published_at(entry)
    published_text = _clean_text(
        entry.get("published") or entry.get("updated") or entry.get("created")
    )

    raw = {
        "feed_url": feed_url,
        "feed_title": feed_title,
        "entry_id": entry_id,
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
    # 把连续空白压缩成一个普通空格，并去掉首尾空白
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text or None
