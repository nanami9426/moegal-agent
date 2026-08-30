from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping, Protocol
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx

from services.rss_pipeline.feeds import RssEntry
from utils.logger import logger


WEEKLY_KIND = "bilibili_weekly"
ANIME_TIMELINE_KIND = "bilibili_anime_timeline"
CATEGORY_RANK_KIND = "bilibili_category_rank"
MALL_NEW_KIND = "bilibili_mall_new"
HOT_SEARCH_KIND = "bilibili_hot_search"
SOURCE_KINDS = frozenset(
    {
        WEEKLY_KIND,
        ANIME_TIMELINE_KIND,
        CATEGORY_RANK_KIND,
        MALL_NEW_KIND,
        HOT_SEARCH_KIND,
    }
)

WEEKLY_SERIES_API_URL = (
    "https://app.bilibili.com/x/v2/show/popular/selected/series"
)
WEEKLY_API_URL = "https://app.bilibili.com/x/v2/show/popular/selected"
ANIME_TIMELINE_API_URL = "https://api.bilibili.com/pgc/web/timeline"
CATEGORY_RANK_API_URL = "https://api.bilibili.com/x/web-interface/newlist_rank"
MALL_NEW_API_URL = "https://mall.bilibili.com/mall-c-search/home/new_items/list"
HOT_SEARCH_API_URL = "https://api.bilibili.com/x/web-interface/search/square"

_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
_CATEGORY_NAMES = {33: "番剧连载", 51: "资讯"}
_MALL_CATEGORY_NAMES = {1: "手办", 3: "周边"}
_BASE_HEADERS = {
    "Accept": "application/json, text/plain, */*",
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
    """根据 kind 采集 Bilibili 的公开列表接口。"""
    kind = str(getattr(source, "kind", ""))
    collectors = {
        WEEKLY_KIND: _collect_weekly,
        ANIME_TIMELINE_KIND: _collect_anime_timeline,
        CATEGORY_RANK_KIND: _collect_category_rank,
        MALL_NEW_KIND: _collect_mall_new,
        HOT_SEARCH_KIND: _collect_hot_search,
    }
    collector = collectors.get(kind)
    if collector is None:
        raise ValueError(
            f"Bilibili 内容源 {getattr(source, 'id', '')!r} 不支持 kind={kind!r}"
        )
    return collector(source, client)


def _collect_weekly(source: _Source, client: httpx.Client) -> list[RssEntry]:
    headers = _headers("https://www.bilibili.com/h5/weekly-recommend")
    series_params = {"type": "weekly_selected"}
    series_response = client.get(
        WEEKLY_SERIES_API_URL,
        params=series_params,
        headers=headers,
    )
    series_response.raise_for_status()
    series_payload = _business_json(series_response, source.id)
    series = _weekly_series(series_payload.get("data"), source.id)
    selected = max(series, key=lambda item: int(item["number"]))
    number = int(selected["number"])

    params = {"type": "weekly_selected", "number": number}
    response = client.get(WEEKLY_API_URL, params=params, headers=headers)
    response.raise_for_status()
    payload = _business_json(response, source.id)
    data = payload.get("data")
    items = data.get("list") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise ValueError(f"Bilibili 内容源 {source.id!r} 的每周必看 list 格式无效")

    request_url = _response_url(response, WEEKLY_API_URL, params)
    series_request_url = _response_url(
        series_response,
        WEEKLY_SERIES_API_URL,
        series_params,
    )
    series_title = _text(selected.get("subject") or selected.get("name"))
    entries: list[RssEntry] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        identity = _video_identity(item)
        if identity is None:
            continue
        reason = _recommendation_reason(item.get("rcmd_reason"))
        video_url = f"https://www.bilibili.com/video/{identity}"
        entries.append(
            RssEntry(
                feed_url=request_url,
                feed_title="B站每周必看",
                entry_id=video_url,
                link=video_url,
                title=_text(item.get("title")),
                summary=_join_text(series_title, reason),
                author=_text(item.get("right_desc_1")),
                published_at=None,
                raw={
                    "source_key": source.id,
                    "source_kind": source.kind,
                    "request_url": request_url,
                    "series_request_url": series_request_url,
                    "weekly_number": number,
                    "weekly_series": selected,
                    "weekly_config": data.get("config"),
                    "video": item,
                },
            )
        )
    return entries


def _collect_anime_timeline(
    source: _Source,
    client: httpx.Client,
) -> list[RssEntry]:
    # 旧版时间表接口会明确标记 is_today，首版固定采集未来一周中的当天番剧。
    params = {"types": 1, "before": 0, "after": 6}
    response = client.get(
        ANIME_TIMELINE_API_URL,
        params=params,
        headers=_headers("https://www.bilibili.com/anime/timeline/"),
    )
    response.raise_for_status()
    payload = _business_json(response, source.id)
    timeline = payload.get("result")
    if not isinstance(timeline, list):
        raise ValueError(f"Bilibili 内容源 {source.id!r} 的番剧时间表格式无效")

    request_url = _response_url(response, ANIME_TIMELINE_API_URL, params)
    today = next(
        (
            day
            for day in timeline
            if isinstance(day, dict) and day.get("is_today") in (1, True, "1")
        ),
        None,
    )
    if today is None:
        raise ValueError(
            f"Bilibili 内容源 {source.id!r} 的番剧时间表缺少今日分组"
        )
    episodes = today.get("episodes")
    if not isinstance(episodes, list):
        raise ValueError(f"Bilibili 内容源 {source.id!r} 的今日番剧 episodes 格式无效")

    entries: list[RssEntry] = []
    seen_episode_ids: set[str] = set()
    for episode in episodes:
        if not isinstance(episode, dict):
            continue
        episode_id = _positive_int_text(episode.get("episode_id"))
        if episode_id is None or episode_id in seen_episode_ids:
            continue
        seen_episode_ids.add(episode_id)
        episode_url = (
            "https://www.bilibili.com/bangumi/play/"
            f"ep{episode_id}"
        )
        entries.append(
            RssEntry(
                feed_url=request_url,
                feed_title="Bilibili 番剧时间表",
                entry_id=episode_url,
                link=episode_url,
                title=_join_text(
                    _text(episode.get("title")),
                    _text(episode.get("pub_index")),
                ),
                summary=_timeline_summary(episode),
                author=None,
                published_at=_unix_timestamp(episode.get("pub_ts")),
                raw={
                    "source_key": source.id,
                    "source_kind": source.kind,
                    "request_url": request_url,
                    "timeline_date": today.get("date"),
                    "timeline_date_ts": today.get("date_ts"),
                    "day_of_week": today.get("day_of_week"),
                    "episode": episode,
                },
            )
        )
    return entries


def _collect_category_rank(
    source: _Source,
    client: httpx.Client,
) -> list[RssEntry]:
    options = _options(source)
    cate_id = _int_option(options, "cate_id")
    days = _int_option(options, "days")
    page_size = _int_option(options, "page_size", default=30)
    if cate_id <= 0:
        raise ValueError(f"Bilibili 内容源 {source.id!r} 的 cate_id 必须大于 0")
    if not 1 <= days <= 30:
        raise ValueError(f"Bilibili 内容源 {source.id!r} 的 days 必须在 1 到 30 之间")
    if not 1 <= page_size <= 50:
        raise ValueError(
            f"Bilibili 内容源 {source.id!r} 的 page_size 必须在 1 到 50 之间"
        )

    today = _today_in_shanghai()
    params = {
        "main_ver": "v3",
        "search_type": "video",
        "view_type": "hot_rank",
        "copy_right": -1,
        "new_web_tag": 1,
        "order": "click",
        "cate_id": cate_id,
        "page": 1,
        "pagesize": page_size,
        "time_from": (today - timedelta(days=days)).strftime("%Y%m%d"),
        "time_to": today.strftime("%Y%m%d"),
    }
    response = client.get(
        CATEGORY_RANK_API_URL,
        params=params,
        headers=_headers(_category_referer(cate_id)),
    )
    response.raise_for_status()
    payload = _business_json(response, source.id)
    data = payload.get("data")
    items = data.get("result") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise ValueError(f"Bilibili 内容源 {source.id!r} 的分区排行 result 格式无效")

    request_url = _response_url(response, CATEGORY_RANK_API_URL, params)
    category_name = _CATEGORY_NAMES.get(cate_id, f"分区 {cate_id}")
    entries: list[RssEntry] = []
    filtered_numeric_count = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        title = _text(item.get("title"))
        # 公开排行偶尔混入纯数字垃圾标题，首版直接过滤，避免污染订阅。
        if title is None or title.isdigit():
            if title is not None and title.isdigit():
                filtered_numeric_count += 1
            continue
        identity = _video_identity(item)
        if identity is None:
            continue
        video_url = f"https://www.bilibili.com/video/{identity}"
        entries.append(
            RssEntry(
                feed_url=request_url,
                feed_title=f"Bilibili {category_name} {days} 日热门",
                entry_id=video_url,
                link=video_url,
                title=title,
                summary=_text(item.get("description")),
                author=_text(item.get("author")),
                published_at=(
                    _unix_timestamp(item.get("senddate"))
                    or _parse_local_datetime(item.get("pubdate"))
                ),
                raw={
                    "source_key": source.id,
                    "source_kind": source.kind,
                    "request_url": request_url,
                    "cate_id": cate_id,
                    "days": days,
                    "page_size": page_size,
                    "order": "click",
                    "video": item,
                },
            )
        )
    if filtered_numeric_count > 0:
        logger.warning(
            "Bilibili 内容源 %s 的分区 %s 过滤了 %s 个纯数字标题",
            source.id,
            cate_id,
            filtered_numeric_count,
        )
    return entries


def _collect_mall_new(source: _Source, client: httpx.Client) -> list[RssEntry]:
    options = _options(source)
    category = _int_option(options, "category")
    if category not in _MALL_CATEGORY_NAMES:
        raise ValueError(f"Bilibili 内容源 {source.id!r} 的 category 只支持 1 或 3")

    params = {
        "pageNum": 1,
        "pageSize": 20,
        "version": "1.0",
        "cityId": 0,
        "cateType": category,
    }
    referer = (
        "https://mall.bilibili.com/newdate.html?"
        "noTitleBar=1&page=new&from=new_product&loadingShow=1"
    )
    response = client.get(
        MALL_NEW_API_URL,
        params=params,
        headers=_headers(referer),
    )
    response.raise_for_status()
    payload = _business_json(response, source.id)
    data = payload.get("data")
    if not isinstance(data, dict) or data.get("codeType") != 1:
        raise ValueError(
            f"Bilibili 内容源 {source.id!r} 的会员购 codeType 必须为 1"
        )
    vo = data.get("vo")
    if not isinstance(vo, dict):
        raise ValueError(f"Bilibili 内容源 {source.id!r} 的会员购 vo 格式无效")

    # 线上 cateTabs 位于 data.vo；若接口返回该字段，必须确认请求分类仍受支持。
    tabs_container = vo if "cateTabs" in vo else data
    if "cateTabs" in tabs_container:
        cate_tabs = tabs_container.get("cateTabs")
        category_exists = isinstance(cate_tabs, list) and any(
            isinstance(tab, dict) and tab.get("cateType") == category
            for tab in cate_tabs
        )
        if not category_exists:
            raise ValueError(
                f"Bilibili 内容源 {source.id!r} 的会员购分类 {category} 不在 cateTabs 中"
            )

    days = vo.get("days")
    if not isinstance(days, list):
        raise ValueError(f"Bilibili 内容源 {source.id!r} 的会员购新品 days 格式无效")

    request_url = _response_url(response, MALL_NEW_API_URL, params)
    entries: list[RssEntry] = []
    seen_item_ids: set[str] = set()
    for day in days:
        if not isinstance(day, dict):
            continue
        items = day.get("presaleItems")
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            item_id = _positive_int_text(item.get("itemsId"))
            if item_id is None or item_id in seen_item_ids:
                continue
            seen_item_ids.add(item_id)
            upstream_item_url = _http_url(item.get("itemUrlForH5"))
            item_url = (
                "https://mall.bilibili.com/detail.html?"
                f"itemsId={quote(item_id)}"
            )
            entries.append(
                RssEntry(
                    feed_url=request_url,
                    feed_title=(
                        f"Bilibili 会员购新品 · {_MALL_CATEGORY_NAMES[category]}"
                    ),
                    entry_id=item_url,
                    link=item_url,
                    title=_text(item.get("name")),
                    summary=_mall_summary(item),
                    author=None,
                    published_at=None,
                    raw={
                        "source_key": source.id,
                        "source_kind": source.kind,
                        "request_url": request_url,
                        "category": category,
                        "day_number": day.get("dayNO"),
                        "week_day": day.get("weekDay"),
                        "upstream_item_url": upstream_item_url,
                        "item": item,
                    },
                )
            )
    return entries


def _collect_hot_search(
    source: _Source,
    client: httpx.Client,
) -> list[RssEntry]:
    params = {"limit": 10, "platform": "web"}
    response = client.get(
        HOT_SEARCH_API_URL,
        params=params,
        headers=_headers("https://www.bilibili.com/"),
    )
    response.raise_for_status()
    payload = _business_json(response, source.id)
    data = payload.get("data")
    trending = data.get("trending") if isinstance(data, dict) else None
    items = trending.get("list") if isinstance(trending, dict) else None
    if not isinstance(items, list):
        raise ValueError(f"Bilibili 内容源 {source.id!r} 的热搜 list 格式无效")

    request_url = _response_url(response, HOT_SEARCH_API_URL, params)
    feed_title = _text(trending.get("title")) or "Bilibili 热搜"
    entries: list[RssEntry] = []
    for position, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        keyword = _text(item.get("keyword") or item.get("show_name"))
        if keyword is None:
            continue
        link = _http_url(item.get("uri")) or (
            "https://search.bilibili.com/all?"
            f"keyword={quote(keyword)}&from_source=webtop_search"
        )
        entries.append(
            RssEntry(
                feed_url=request_url,
                feed_title=feed_title,
                entry_id=link,
                link=link,
                title=keyword,
                summary=_text(item.get("show_name")),
                author=None,
                published_at=None,
                raw={
                    "source_key": source.id,
                    "source_kind": source.kind,
                    "request_url": request_url,
                    "rank_position": position,
                    "keyword": keyword,
                    "heat_score": item.get("heat_score"),
                    "icon": item.get("icon"),
                    "goto": item.get("goto"),
                    "uri": item.get("uri"),
                },
            )
        )
    return entries


def _weekly_series(data: Any, source_id: str) -> list[dict[str, Any]]:
    raw_series = data.get("list") if isinstance(data, dict) else data
    if not isinstance(raw_series, list):
        raise ValueError(f"Bilibili 内容源 {source_id!r} 的每周必看期数格式无效")

    result: list[dict[str, Any]] = []
    for item in raw_series:
        if not isinstance(item, dict) or isinstance(item.get("number"), bool):
            continue
        try:
            number = int(item.get("number"))
        except (TypeError, ValueError):
            continue
        if number > 0:
            result.append({**item, "number": number})
    if not result:
        raise ValueError(f"Bilibili 内容源 {source_id!r} 没有可用的每周必看期数")
    return result


def _business_json(response: httpx.Response, source_id: str) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise ValueError(f"Bilibili 内容源 {source_id!r} 返回了无效 JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Bilibili 内容源 {source_id!r} 返回的 JSON 顶层不是对象")
    if payload.get("code") != 0:
        message = payload.get("message") or payload.get("msg")
        raise ValueError(
            f"Bilibili 内容源 {source_id!r} 返回业务错误: "
            f"code={payload.get('code')!r}, message={message!r}"
        )
    return payload


def _options(source: _Source) -> Mapping[str, Any]:
    options = getattr(source, "options", {})
    return options if isinstance(options, Mapping) else {}


def _int_option(
    options: Mapping[str, Any],
    key: str,
    *,
    default: int | None = None,
) -> int:
    value = options.get(key, default)
    if isinstance(value, bool):
        raise ValueError(f"Bilibili 内容源选项 {key!r} 必须是整数")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Bilibili 内容源选项 {key!r} 必须是整数") from exc


def _headers(referer: str) -> dict[str, str]:
    return {**_BASE_HEADERS, "Referer": referer}


def _category_referer(tid: int) -> str:
    if tid == 33:
        return "https://www.bilibili.com/v/anime/serial/"
    if tid == 51:
        return "https://www.bilibili.com/v/anime/information/"
    return "https://www.bilibili.com/"


def _response_url(
    response: httpx.Response,
    fallback: str,
    params: Mapping[str, Any],
) -> str:
    request = getattr(response, "request", None)
    url = getattr(request, "url", None)
    return str(url) if url is not None else str(httpx.URL(fallback, params=params))


def _today_in_shanghai() -> date:
    return datetime.now(_SHANGHAI_TZ).date()


def _video_identity(item: Mapping[str, Any]) -> str | None:
    bvid = _text(item.get("bvid"))
    if bvid:
        return bvid
    param = _text(item.get("param") or item.get("id"))
    if param is None:
        return None
    return param if param.lower().startswith(("av", "bv")) else f"av{param}"


def _recommendation_reason(value: Any) -> str | None:
    if isinstance(value, dict):
        return _text(value.get("content") or value.get("text"))
    return _text(value)


def _timeline_summary(episode: Mapping[str, Any]) -> str | None:
    return _join_text(
        _text(episode.get("pub_time")),
        _text(episode.get("delay_reason")),
    )


def _mall_summary(item: Mapping[str, Any]) -> str | None:
    price = _text(item.get("priceDesc"))
    if price is None:
        symbol = _text(item.get("priceSymbol")) or ""
        value = _text(item.get("price"))
        price = f"{symbol}{value}" if value else None
    return _join_text(_text(item.get("brief")), price)


def _http_url(value: Any) -> str | None:
    text = _text(value)
    if text is None:
        return None
    if text.startswith("//"):
        return f"https:{text}"
    if text.startswith(("https://", "http://")):
        return text
    return None


def _positive_int_text(value: Any) -> str | None:
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return str(number) if number > 0 else None


def _unix_timestamp(value: Any) -> datetime | None:
    if isinstance(value, bool):
        return None
    try:
        timestamp = int(value)
    except (TypeError, ValueError):
        return None
    if timestamp <= 0:
        return None
    try:
        return datetime.fromtimestamp(timestamp, timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _parse_local_datetime(value: Any) -> datetime | None:
    text = _text(value)
    if text is None:
        return None
    for date_format in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(text, date_format).replace(tzinfo=_SHANGHAI_TZ)
        except ValueError:
            continue
        return parsed.astimezone(timezone.utc)
    return None


def _join_text(*values: str | None) -> str | None:
    parts = [value for value in values if value]
    return " · ".join(parts) or None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    result = " ".join(str(value).split())
    return result or None
