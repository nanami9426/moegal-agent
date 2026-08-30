from datetime import datetime, timezone
from typing import Any, Mapping, Protocol

import httpx

from services.rss_pipeline.feeds import RssEntry


SOURCE_KIND = "mihoyo_official"
API_URL = "https://bbs-api.miyoushe.com/post/api/getNewsList"

_GAME_NAMES = {
    2: "原神",
    6: "崩坏：星穹铁道",
    8: "绝区零",
}
_GAME_SLUGS = {
    2: "ys",
    6: "sr",
    8: "zzz",
}
_NEWS_TYPE_NAMES = {
    1: "公告",
    2: "活动",
}
_REQUEST_HEADERS = {
    "Accept": "application/json",
    "Referer": "https://www.miyoushe.com/",
}


class _Source(Protocol):
    id: str
    kind: str
    options: Mapping[str, Any]


def collect(source: _Source, client: httpx.Client) -> list[RssEntry]:
    """采集一个米游社游戏与官方内容类型组合的最新条目。"""
    options = source.options
    gids = _read_int_option(options, "gids")
    news_type = _read_int_option(options, "news_type")
    page_size = _read_int_option(options, "page_size", default=20)

    if gids not in _GAME_NAMES:
        raise ValueError(f"米游社内容源 {source.id!r} 的 gids 不受支持: {gids}")
    if news_type not in _NEWS_TYPE_NAMES:
        raise ValueError(
            f"米游社内容源 {source.id!r} 的 news_type 不受支持: {news_type}"
        )
    if not 1 <= page_size <= 50:
        raise ValueError(
            f"米游社内容源 {source.id!r} 的 page_size 必须在 1 到 50 之间"
        )

    response = client.get(
        API_URL,
        params={"gids": gids, "type": news_type, "page_size": page_size},
        headers=_REQUEST_HEADERS,
    )
    response.raise_for_status()
    payload = _response_json(response, source.id)

    if payload.get("retcode") != 0:
        raise ValueError(
            f"米游社内容源 {source.id!r} 返回业务错误: "
            f"retcode={payload.get('retcode')!r}, message={payload.get('message')!r}"
        )

    data = payload.get("data")
    items = data.get("list") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise ValueError(f"米游社内容源 {source.id!r} 的 data.list 格式无效")

    request_url = str(response.request.url)
    return [
        _to_rss_entry(
            item,
            source=source,
            gids=gids,
            news_type=news_type,
            request_url=request_url,
        )
        for item in items
    ]


def _to_rss_entry(
    item: Any,
    *,
    source: _Source,
    gids: int,
    news_type: int,
    request_url: str,
) -> RssEntry:
    if not isinstance(item, dict) or not isinstance(item.get("post"), dict):
        raise ValueError(f"米游社内容源 {source.id!r} 返回了无效的帖子数据")

    post = item["post"]
    post_id = _text(post.get("post_id"))
    if post_id is None:
        raise ValueError(f"米游社内容源 {source.id!r} 的帖子缺少 post_id")

    game_name = _GAME_NAMES[gids]
    news_type_name = _NEWS_TYPE_NAMES[news_type]
    game_slug = _GAME_SLUGS[gids]
    article_url = f"https://www.miyoushe.com/{game_slug}/article/{post_id}"

    # 列表接口会裁剪正文和作者，因此首版只保存标题级数据，避免逐条请求详情。
    return RssEntry(
        feed_url=request_url,
        feed_title=f"{game_name}官方{news_type_name}",
        entry_id=article_url,
        link=article_url,
        title=_text(post.get("subject")),
        summary=None,
        author=f"{game_name}官方",
        published_at=_unix_timestamp(post.get("created_at")),
        raw={
            "source_key": source.id,
            "source_kind": source.kind,
            "request_url": request_url,
            "gids": gids,
            "news_type": news_type,
            "post_id": post_id,
            "cover": _text(post.get("cover")),
            "images": (
                post.get("images")
                if isinstance(post.get("images"), list)
                else []
            ),
            "news_meta": item.get("news_meta"),
        },
    )


def _read_int_option(
    options: Mapping[str, Any],
    key: str,
    *,
    default: int | None = None,
) -> int:
    value = options.get(key, default)
    if isinstance(value, bool):
        raise ValueError(f"米游社内容源选项 {key!r} 必须是整数")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"米游社内容源选项 {key!r} 必须是整数") from exc


def _response_json(response: httpx.Response, source_id: str) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise ValueError(f"米游社内容源 {source_id!r} 返回了无效 JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"米游社内容源 {source_id!r} 返回的 JSON 顶层不是对象")
    return payload


def _text(value: Any) -> str | None:
    if value is None:
        return None
    result = " ".join(str(value).split())
    return result or None


def _unix_timestamp(value: Any) -> datetime | None:
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
