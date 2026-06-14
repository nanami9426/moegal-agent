import calendar
import html
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import feedparser
import httpx

from config.paths import RSS_FEEDS_CONFIG_PATH

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")
RSS_FETCH_CONCURRENCY_ENV = "MOEGAL_RSS_FETCH_CONCURRENCY"
DEFAULT_RSS_FETCH_CONCURRENCY = 8
MAX_RSS_FETCH_CONCURRENCY = 32
RSS_FETCH_TIMEOUT_SECONDS = 15.0


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


@dataclass(frozen=True)
class _SingleFeedFetchResult:
    entries: list[RssEntry]
    errors: list[RssFetchError]


def get_configured_feed_urls() -> list[str]:
    if not RSS_FEEDS_CONFIG_PATH.exists():
        return []

    base_url = _rsshub_base_url()
    access_key = os.getenv("MOEGAL_RSSHUB_ACCESS_KEY", "moegal_rsshub")
    urls: list[str] = []

    for line in RSS_FEEDS_CONFIG_PATH.read_text(encoding="utf-8").splitlines():
        feed = line.strip()
        if not feed or feed.startswith("#"):
            continue
        urls.append(_build_feed_url(feed, base_url=base_url, access_key=access_key))

    return urls


def fetch_rss_entries(feed_urls: list[str] | None = None) -> RssFetchResult:
    # 从一组 RSS/RSSHub URL 抓取内容，解析成统一的 RssEntry 列表
    # 同时把失败的源记录到 errors，最后一起返回。
    urls = list(feed_urls) if feed_urls is not None else get_configured_feed_urls()
    entries: list[RssEntry] = [] # 成功解析出来的 RSS 条目
    errors: list[RssFetchError] = [] # 抓取失败或解析失败的 feed

    if not urls:
        return RssFetchResult(entries=entries, errors=errors)

    results: list[_SingleFeedFetchResult | None] = [None] * len(urls)
    max_workers = _rss_fetch_concurrency(len(urls))

    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="rss-fetch") as executor:
        future_to_index = {
            executor.submit(_fetch_single_feed_entries, feed_url): index
            for index, feed_url in enumerate(urls)
        }
        for future in as_completed(future_to_index):
            index = future_to_index[future]
            feed_url = urls[index]
            try:
                results[index] = future.result()
            except Exception as exc:
                results[index] = _SingleFeedFetchResult(
                    entries=[],
                    errors=[RssFetchError(feed_url=feed_url, message=str(exc))],
                )

    for result in results:
        if result is None:
            continue
        entries.extend(result.entries)
        errors.extend(result.errors)

    return RssFetchResult(entries=entries, errors=errors)


def _fetch_single_feed_entries(feed_url: str) -> _SingleFeedFetchResult:
    try:
        response = httpx.get(
            feed_url,
            follow_redirects=True,
            timeout=RSS_FETCH_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        return _SingleFeedFetchResult(
            entries=[],
            errors=[RssFetchError(feed_url=feed_url, message=str(exc))],
        )

    # 用 feedparser 解析 RSS/Atom 内容
    parsed = feedparser.parse(response.content)
    if parsed.bozo and not parsed.entries:
        # feedparser 的 bozo 表示这个 feed 有解析异常
        # 如果解析失败且没有条目，就记录错误，然后跳过
        return _SingleFeedFetchResult(
            entries=[],
            errors=[
                RssFetchError(
                    feed_url=feed_url,
                    message=str(getattr(parsed, "bozo_exception", "invalid feed")),
                )
            ],
        )

    feed_title = _clean_text(parsed.feed.get("title"))
    return _SingleFeedFetchResult(
        entries=[_normalize_entry(feed_url, feed_title, entry) for entry in parsed.entries],
        errors=[],
    )


def _rss_fetch_concurrency(feed_count: int) -> int:
    raw_value = os.getenv(RSS_FETCH_CONCURRENCY_ENV)
    if raw_value is None or raw_value.strip() == "":
        configured_concurrency = DEFAULT_RSS_FETCH_CONCURRENCY
    else:
        try:
            configured_concurrency = int(raw_value)
        except ValueError:
            configured_concurrency = DEFAULT_RSS_FETCH_CONCURRENCY

    configured_concurrency = max(1, min(configured_concurrency, MAX_RSS_FETCH_CONCURRENCY))
    return max(1, min(feed_count, configured_concurrency))


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


def _rsshub_base_url() -> str:
    base_url = os.getenv("MOEGAL_RSSHUB_BASE_URL", "http://127.0.0.1:1200").strip().rstrip("/")
    if not base_url:
        base_url = "http://127.0.0.1:1200"
    if "://" not in base_url:
        base_url = f"http://{base_url}"
    return base_url


def _build_feed_url(feed: str, *, base_url: str, access_key: str) -> str:
    if feed.startswith(("http://", "https://")):
        url = feed
    else:
        path = feed if feed.startswith("/") else f"/{feed}"
        url = f"{base_url}{path}"

    if not access_key:
        return url

    parsed_url = urlparse(url)
    query = dict(parse_qsl(parsed_url.query, keep_blank_values=True))
    query.setdefault("key", access_key)
    return urlunparse(parsed_url._replace(query=urlencode(query)))
