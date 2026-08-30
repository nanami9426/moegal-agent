from datetime import datetime, timezone
from typing import Any, Mapping, Protocol

import httpx

from services.rss_pipeline.feeds import RssEntry


SOURCE_KIND = "arknights_news"
API_URL = "https://ak.hypergryph.com/api/news"
MAX_PAGES = 10

_REQUEST_HEADERS = {
    "Accept": "application/json",
}
_CATEGORY_NAMES = {
    "0": "公告",
    "1": "活动",
    "2": "新闻",
}


class _Source(Protocol):
    id: str
    kind: str
    options: Mapping[str, Any]


def collect(source: _Source, client: httpx.Client) -> list[RssEntry]:
    """采集明日方舟官网“最新”栏目，最多读取十页。"""
    entries: list[RssEntry] = []
    seen_ids: set[str] = set()

    for page in range(1, MAX_PAGES + 1):
        response = client.get(
            API_URL,
            params={"category": "LATEST", "page": page},
            headers=_REQUEST_HEADERS,
        )
        response.raise_for_status()
        payload = _response_json(response, source.id)

        if payload.get("code") != 0:
            raise ValueError(
                f"明日方舟内容源 {source.id!r} 返回业务错误: "
                f"code={payload.get('code')!r}, message={payload.get('msg')!r}"
            )

        data = payload.get("data")
        items = data.get("list") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise ValueError(f"明日方舟内容源 {source.id!r} 的 data.list 格式无效")

        request_url = str(response.request.url)
        for item in items:
            entry = _to_rss_entry(
                item,
                source=source,
                page=page,
                request_url=request_url,
            )
            entry_id = entry.entry_id
            if entry_id is None or entry_id in seen_ids:
                continue
            seen_ids.add(entry_id)
            entries.append(entry)

        # 官网用 end 明确标记末页；达到十页时也会由循环上限主动停止。
        if data.get("end") is True:
            break

    return entries


def _to_rss_entry(
    item: Any,
    *,
    source: _Source,
    page: int,
    request_url: str,
) -> RssEntry:
    if not isinstance(item, dict):
        raise ValueError(f"明日方舟内容源 {source.id!r} 返回了无效的新闻数据")

    cid = _text(item.get("cid"))
    if cid is None:
        raise ValueError(f"明日方舟内容源 {source.id!r} 的新闻缺少 cid")

    tab = _text(item.get("tab"))
    article_url = f"https://ak.hypergryph.com/news/{cid}"
    return RssEntry(
        feed_url=request_url,
        feed_title="明日方舟最新情报",
        entry_id=article_url,
        link=article_url,
        title=_text(item.get("title")),
        summary=_text(item.get("brief")),
        author=_text(item.get("author")),
        published_at=_unix_timestamp(item.get("displayTime")),
        raw={
            "source_key": source.id,
            "source_kind": source.kind,
            "request_url": request_url,
            "cid": cid,
            "category": _CATEGORY_NAMES.get(tab, "最新"),
            "tab": tab,
            "page": page,
            "cover": _text(item.get("cover")),
            "extra_cover": _text(item.get("extraCover")),
            "sticky": bool(item.get("sticky")),
        },
    )


def _response_json(response: httpx.Response, source_id: str) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise ValueError(f"明日方舟内容源 {source_id!r} 返回了无效 JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"明日方舟内容源 {source_id!r} 返回的 JSON 顶层不是对象")
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
