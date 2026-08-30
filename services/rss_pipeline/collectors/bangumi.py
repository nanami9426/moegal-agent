from __future__ import annotations

import os
import re
from datetime import date, datetime, time, timezone
from typing import Any, Mapping, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from bs4 import BeautifulSoup

from services.rss_pipeline.feeds import RssEntry


CALENDAR_TODAY_KIND = "bangumi_calendar_today"
TRENDING_KIND = "bangumi_anime_trending"
SOURCE_KINDS = frozenset({CALENDAR_TODAY_KIND, TRENDING_KIND})

CALENDAR_API_URL = "https://api.bgm.tv/calendar"
ANIME_HOME_URL = "https://bgm.tv/anime"

_DEFAULT_TIMEZONE = "Asia/Shanghai"
_SUBJECT_PATH_RE = re.compile(r"^/subject/(\d+)(?:[/?#]|$)")
_COVER_URL_RE = re.compile(r"url\((?:['\"])?(.+?)(?:['\"])?\)", re.I)
_FOLLOWER_COUNT_RE = re.compile(r"([\d,]+)\s*人")
_CALENDAR_HEADERS = {"Accept": "application/json"}
_TRENDING_HEADERS = {
    "Accept": "text/html,application/xhtml+xml",
    # 动画首页会拦截非浏览器 UA；官方 API 仍沿用 Client 中可配置的应用 UA。
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
}


class _Source(Protocol):
    id: str
    kind: str
    options: Mapping[str, Any]


def collect(source: _Source, client: httpx.Client) -> list[RssEntry]:
    """采集 Bangumi 每日放送或动画关注榜。"""
    kind = str(getattr(source, "kind", ""))
    if kind == CALENDAR_TODAY_KIND:
        return _collect_calendar_today(source, client)
    if kind == TRENDING_KIND:
        return _collect_trending(source, client)
    raise ValueError(f"Bangumi 内容源 {getattr(source, 'id', '')!r} 不支持 kind={kind!r}")


def _collect_calendar_today(
    source: _Source,
    client: httpx.Client,
) -> list[RssEntry]:
    response = client.get(CALENDAR_API_URL, headers=_CALENDAR_HEADERS)
    response.raise_for_status()
    payload = _response_json(response, source.id)
    if not isinstance(payload, list):
        raise ValueError(f"Bangumi 内容源 {source.id!r} 的日历 JSON 顶层不是数组")

    calendar_timezone = _configured_timezone()
    today = _today_in_timezone(calendar_timezone)
    weekday_group = next(
        (
            group
            for group in payload
            if isinstance(group, dict)
            and isinstance(group.get("weekday"), dict)
            and group["weekday"].get("id") == today.isoweekday()
        ),
        None,
    )
    if weekday_group is None:
        raise ValueError(
            f"Bangumi 内容源 {source.id!r} 的日历缺少当天 weekday 分组"
        )

    items = weekday_group.get("items")
    if not isinstance(items, list):
        raise ValueError(f"Bangumi 内容源 {source.id!r} 的日历 items 格式无效")

    request_url = _response_url(response, CALENDAR_API_URL)
    published_at = datetime.combine(
        today,
        time.min,
        tzinfo=calendar_timezone,
    ).astimezone(timezone.utc)
    entries: list[RssEntry] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        subject_id = _positive_int_text(item.get("id"))
        if subject_id is None:
            continue

        name = _text(item.get("name"))
        name_cn = _text(item.get("name_cn"))
        title = name_cn if not name or name_cn == name else _join_text(name_cn, name)
        subject_url = f"https://bgm.tv/subject/{subject_id}"
        entries.append(
            RssEntry(
                feed_url=request_url,
                feed_title="Bangumi 每日放送",
                # 同一作品每周重复放送，因此日期也是稳定身份的一部分。
                entry_id=f"{subject_url}#{today.isoformat()}",
                link=subject_url,
                title=title,
                summary=_text(item.get("summary")),
                author=None,
                published_at=published_at,
                raw={
                    "source_key": source.id,
                    "source_kind": source.kind,
                    "request_url": request_url,
                    "subject_id": subject_id,
                    "calendar_date": today.isoformat(),
                    "published_at_inferred": True,
                    "weekday": weekday_group.get("weekday"),
                    "subject": item,
                },
            )
        )
    return entries


def _collect_trending(
    source: _Source,
    client: httpx.Client,
) -> list[RssEntry]:
    response = client.get(ANIME_HOME_URL, headers=_TRENDING_HEADERS)
    response.raise_for_status()

    # featuredItems 是 Bangumi 动画首页的成员关注榜，限定选择器可避免误收其他作品。
    soup = BeautifulSoup(response.text, "html.parser")
    request_url = _response_url(response, ANIME_HOME_URL)

    main_items = soup.select("ul.featuredItems .mainItem")
    if not main_items:
        raise ValueError(
            f"Bangumi 内容源 {source.id!r} 的动画页缺少注目动画列表"
        )

    entries: list[RssEntry] = []
    for position, main_item in enumerate(main_items, start=1):
        subject_link = main_item.select_one('a[href^="/subject/"]')
        href = subject_link.get("href") if subject_link is not None else None
        match = _SUBJECT_PATH_RE.match(href) if isinstance(href, str) else None
        if match is None:
            continue

        subject_id = match.group(1)
        subject_url = f"https://bgm.tv/subject/{subject_id}"
        title_link = main_item.select_one("p.title a")
        title = _text(subject_link.get("title"))
        if title is None and title_link is not None:
            title = _text(title_link.get_text(" ", strip=True))
        followers_node = main_item.select_one("small.grey")
        followers = (
            _text(followers_node.get_text(" ", strip=True))
            if followers_node is not None
            else None
        )
        cover_node = main_item.select_one(".image")
        cover_style = cover_node.get("style") if cover_node is not None else None
        cover = _cover_from_style(cover_style if isinstance(cover_style, str) else None)
        entries.append(
            RssEntry(
                feed_url=request_url,
                feed_title="BangumiTV 成员关注动画榜",
                entry_id=subject_url,
                link=subject_url,
                title=title,
                summary=followers,
                author=None,
                # 榜单页不提供可靠的上榜时间，不能用抓取时间伪造发布时间。
                published_at=None,
                raw={
                    "source_key": source.id,
                    "source_kind": source.kind,
                    "request_url": request_url,
                    "subject_id": subject_id,
                    "rank_position": position,
                    "followers": followers,
                    "follower_count": _follower_count(followers),
                    "cover": cover,
                },
            )
        )
    return entries


def _response_json(response: httpx.Response, source_id: str) -> Any:
    try:
        return response.json()
    except ValueError as exc:
        raise ValueError(f"Bangumi 内容源 {source_id!r} 返回了无效 JSON") from exc


def _response_url(response: httpx.Response, fallback: str) -> str:
    request = getattr(response, "request", None)
    url = getattr(request, "url", None)
    return str(url) if url is not None else fallback


def _configured_timezone() -> ZoneInfo:
    timezone_name = (os.getenv("MOEGAL_TIMEZONE") or "").strip() or _DEFAULT_TIMEZONE
    try:
        return ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(_DEFAULT_TIMEZONE)


def _today_in_timezone(timezone_info: ZoneInfo) -> date:
    return datetime.now(timezone_info).date()


def _cover_from_style(style: str | None) -> str | None:
    if not style:
        return None
    match = _COVER_URL_RE.search(style)
    if not match:
        return None
    cover = match.group(1).strip()
    if cover.startswith("//"):
        return f"https:{cover}"
    return cover or None


def _follower_count(value: Any) -> int | None:
    text = _text(value)
    if text is None:
        return None
    match = _FOLLOWER_COUNT_RE.search(text)
    if not match:
        return None
    return int(match.group(1).replace(",", ""))


def _positive_int_text(value: Any) -> str | None:
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return str(number) if number > 0 else None


def _join_text(*values: str | None) -> str | None:
    parts = [value for value in values if value]
    return "｜".join(parts) or None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    result = " ".join(str(value).split())
    return result or None
