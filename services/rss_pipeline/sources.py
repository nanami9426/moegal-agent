import os
import re
import threading
import tomllib
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from config.paths import CONTENT_SOURCES_CONFIG_PATH
from services.rss_pipeline.feeds import RssEntry


CONTENT_SOURCES_CONFIG_VERSION = 1
RSS_FETCH_CONCURRENCY_ENV = "MOEGAL_RSS_FETCH_CONCURRENCY"
CONTENT_USER_AGENT_ENV = "MOEGAL_CONTENT_USER_AGENT"
DEFAULT_RSS_FETCH_CONCURRENCY = 8
MAX_RSS_FETCH_CONCURRENCY = 32
RSS_FETCH_TIMEOUT_SECONDS = 15.0
DEFAULT_CONTENT_USER_AGENT = "Moegal-Agent/0.1"

_SOURCE_ID_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")
_COMMON_SOURCE_FIELDS = frozenset({"id", "kind", "enabled"})

_BANGUMI_KINDS = frozenset(
    {"bangumi_calendar_today", "bangumi_anime_trending"}
)
_BILIBILI_KINDS = frozenset(
    {
        "bilibili_weekly",
        "bilibili_anime_timeline",
        "bilibili_category_rank",
        "bilibili_mall_new",
        "bilibili_hot_search",
    }
)
_MIHOYO_KINDS = frozenset({"mihoyo_official"})
_ARKNIGHTS_KINDS = frozenset({"arknights_news"})
_SUPPORTED_KINDS = frozenset(
    {
        "feed",
        *_BANGUMI_KINDS,
        *_BILIBILI_KINDS,
        *_MIHOYO_KINDS,
        *_ARKNIGHTS_KINDS,
    }
)

_REQUIRED_OPTION_FIELDS: dict[str, frozenset[str]] = {
    "feed": frozenset({"url"}),
    "bangumi_calendar_today": frozenset(),
    "bangumi_anime_trending": frozenset(),
    "bilibili_weekly": frozenset(),
    "bilibili_anime_timeline": frozenset(),
    "bilibili_category_rank": frozenset({"cate_id", "days", "page_size"}),
    "bilibili_mall_new": frozenset({"category"}),
    "bilibili_hot_search": frozenset(),
    "mihoyo_official": frozenset({"gids", "news_type", "page_size"}),
    "arknights_news": frozenset(),
}
@dataclass(frozen=True)
class ContentSource:
    id: str
    kind: str
    enabled: bool = True
    options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SourceFetchError:
    source_id: str
    source_kind: str
    message: str


@dataclass(frozen=True)
class SourceFetchResult:
    entries: list[RssEntry]
    errors: list[SourceFetchError]
    source_count: int
    successful_source_count: int


def load_content_sources(
    path: str | Path | None = None,
) -> list[ContentSource]:
    """读取并严格校验内容源配置，只返回启用的来源。"""
    config_path = CONTENT_SOURCES_CONFIG_PATH if path is None else Path(path)
    try:
        config_text = config_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []

    try:
        config = tomllib.loads(config_text)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"内容源配置不是有效的 TOML: {config_path}: {exc}") from exc

    sources = _parse_content_sources(config, config_path)
    return [source for source in sources if source.enabled]


def collect_content_sources(
    sources: list[ContentSource] | None = None,
) -> SourceFetchResult:
    """并发采集内容源；单个来源失败不会影响其他来源。"""
    configured_sources = load_content_sources() if sources is None else list(sources)
    enabled_sources = [source for source in configured_sources if source.enabled]
    if not enabled_sources:
        return SourceFetchResult(
            entries=[],
            errors=[],
            source_count=0,
            successful_source_count=0,
        )

    # Bilibili 和米游社接口对并发较敏感，单独限制同平台最多两个来源并行。
    platform_semaphores = {
        "bilibili": threading.Semaphore(2),
        "mihoyo": threading.Semaphore(2),
    }
    ordered_results: list[list[RssEntry] | SourceFetchError | None] = [
        None
    ] * len(enabled_sources)
    max_workers = _source_fetch_concurrency(len(enabled_sources))

    with httpx.Client(
        follow_redirects=True,
        timeout=RSS_FETCH_TIMEOUT_SECONDS,
        headers={"User-Agent": _content_user_agent()},
    ) as client:
        with ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="content-source-fetch",
        ) as executor:
            future_to_index = {
                executor.submit(
                    _collect_single_source,
                    source,
                    client,
                    platform_semaphores,
                ): index
                for index, source in enumerate(enabled_sources)
            }

            for future in as_completed(future_to_index):
                index = future_to_index[future]
                source = enabled_sources[index]
                try:
                    entries = future.result()
                    if not isinstance(entries, list):
                        raise TypeError("collector must return list[RssEntry]")
                    ordered_results[index] = entries
                except Exception as exc:
                    ordered_results[index] = SourceFetchError(
                        source_id=source.id,
                        source_kind=source.kind,
                        message=str(exc) or type(exc).__name__,
                    )

    entries: list[RssEntry] = []
    errors: list[SourceFetchError] = []
    successful_source_count = 0
    for result in ordered_results:
        if isinstance(result, SourceFetchError):
            errors.append(result)
        elif result is not None:
            entries.extend(result)
            successful_source_count += 1

    return SourceFetchResult(
        entries=entries,
        errors=errors,
        source_count=len(enabled_sources),
        successful_source_count=successful_source_count,
    )


def _parse_content_sources(config: dict[str, Any], path: Path) -> list[ContentSource]:
    unknown_top_level_fields = set(config) - {"version", "sources"}
    if unknown_top_level_fields:
        fields = ", ".join(sorted(unknown_top_level_fields))
        raise ValueError(f"内容源配置包含未知顶层字段: {fields}")

    version = config.get("version")
    if type(version) is not int or version != CONTENT_SOURCES_CONFIG_VERSION:
        raise ValueError(
            f"内容源配置 {path} 的 version 必须为 {CONTENT_SOURCES_CONFIG_VERSION}"
        )

    raw_sources = config.get("sources", [])
    if not isinstance(raw_sources, list):
        raise ValueError("内容源配置的 sources 必须是 TOML 表数组")

    sources: list[ContentSource] = []
    source_ids: set[str] = set()
    for index, raw_source in enumerate(raw_sources):
        location = f"sources[{index}]"
        if not isinstance(raw_source, dict):
            raise ValueError(f"{location} 必须是 TOML 表")

        source = _parse_content_source(raw_source, location)
        if source.id in source_ids:
            raise ValueError(f"内容源 id 重复: {source.id}")
        source_ids.add(source.id)
        sources.append(source)

    return sources


def _parse_content_source(raw_source: dict[str, Any], location: str) -> ContentSource:
    source_id = raw_source.get("id")
    if not isinstance(source_id, str) or not _SOURCE_ID_RE.fullmatch(source_id):
        raise ValueError(
            f"{location}.id 必须匹配 [a-z0-9][a-z0-9_-]{{0,63}}"
        )

    kind = raw_source.get("kind")
    if not isinstance(kind, str) or kind not in _SUPPORTED_KINDS:
        supported = ", ".join(sorted(_SUPPORTED_KINDS))
        raise ValueError(f"{location}.kind 不支持 {kind!r}，可选值: {supported}")

    enabled = raw_source.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ValueError(f"{location}.enabled 必须是布尔值")

    required_fields = _REQUIRED_OPTION_FIELDS[kind]
    allowed_fields = _COMMON_SOURCE_FIELDS | required_fields
    unknown_fields = set(raw_source) - allowed_fields
    if unknown_fields:
        fields = ", ".join(sorted(unknown_fields))
        raise ValueError(f"{location} 包含 {kind} 不支持的字段: {fields}")

    missing_fields = required_fields - set(raw_source)
    if missing_fields:
        fields = ", ".join(sorted(missing_fields))
        raise ValueError(f"{location} 缺少 {kind} 必填字段: {fields}")

    options = {
        key: raw_source[key]
        for key in required_fields
        if key in raw_source
    }
    _validate_source_options(kind, options, location)
    return ContentSource(
        id=source_id,
        kind=kind,
        enabled=enabled,
        options=options,
    )


def _validate_source_options(
    kind: str,
    options: dict[str, Any],
    location: str,
) -> None:
    if kind == "feed":
        url = options["url"]
        if not isinstance(url, str):
            raise ValueError(f"{location}.url 必须是字符串")
        if any(character.isspace() for character in url):
            raise ValueError(f"{location}.url 必须是绝对 HTTP(S) URL")
        try:
            parsed_url = httpx.URL(url)
        except (httpx.InvalidURL, ValueError) as exc:
            raise ValueError(f"{location}.url 必须是绝对 HTTP(S) URL") from exc
        if (
            parsed_url.scheme not in {"http", "https"}
            or not parsed_url.is_absolute_url
            or not parsed_url.host
        ):
            raise ValueError(f"{location}.url 必须是绝对 HTTP(S) URL")
        return

    if kind == "bilibili_category_rank":
        _require_int_range(options, "cate_id", 1, 2**31 - 1, location)
        _require_int_range(options, "days", 1, 30, location)
        _require_int_range(options, "page_size", 1, 50, location)
        return

    if kind == "bilibili_mall_new":
        _require_int_in(options, "category", {1, 3}, location)
        return

    if kind == "mihoyo_official":
        _require_int_in(options, "gids", {2, 6, 8}, location)
        _require_int_in(options, "news_type", {1, 2}, location)
        _require_int_range(options, "page_size", 1, 50, location)


def _require_int_in(
    options: dict[str, Any],
    field_name: str,
    allowed_values: set[int],
    location: str,
) -> None:
    value = options.get(field_name)
    if type(value) is not int or value not in allowed_values:
        allowed = ", ".join(str(item) for item in sorted(allowed_values))
        raise ValueError(f"{location}.{field_name} 必须是以下整数之一: {allowed}")


def _require_int_range(
    options: dict[str, Any],
    field_name: str,
    minimum: int,
    maximum: int,
    location: str,
    *,
    required: bool = True,
) -> None:
    if not required and field_name not in options:
        return

    value = options.get(field_name)
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(
            f"{location}.{field_name} 必须是 {minimum} 到 {maximum} 之间的整数"
        )


def _source_fetch_concurrency(source_count: int) -> int:
    raw_value = os.getenv(RSS_FETCH_CONCURRENCY_ENV)
    if raw_value is None or raw_value.strip() == "":
        configured_concurrency = DEFAULT_RSS_FETCH_CONCURRENCY
    else:
        try:
            configured_concurrency = int(raw_value)
        except ValueError:
            configured_concurrency = DEFAULT_RSS_FETCH_CONCURRENCY

    configured_concurrency = max(
        1,
        min(configured_concurrency, MAX_RSS_FETCH_CONCURRENCY),
    )
    return max(1, min(source_count, configured_concurrency))


def _content_user_agent() -> str:
    configured_user_agent = os.getenv(CONTENT_USER_AGENT_ENV, "").strip()
    return configured_user_agent or DEFAULT_CONTENT_USER_AGENT


def _collect_single_source(
    source: ContentSource,
    client: httpx.Client,
    platform_semaphores: dict[str, threading.Semaphore],
) -> list[RssEntry]:
    platform = _platform_for_kind(source.kind)
    semaphore = platform_semaphores.get(platform)
    if semaphore is None:
        return _invoke_collector(source, client)

    with semaphore:
        return _invoke_collector(source, client)


def _platform_for_kind(kind: str) -> str:
    if kind in _BILIBILI_KINDS:
        return "bilibili"
    if kind in _MIHOYO_KINDS:
        return "mihoyo"
    if kind in _BANGUMI_KINDS:
        return "bangumi"
    if kind in _ARKNIGHTS_KINDS:
        return "arknights"
    return "feed"


def _invoke_collector(
    source: ContentSource,
    client: httpx.Client,
) -> list[RssEntry]:
    # 按 kind 做简单分发，避免为数量有限的平台引入抽象基类。
    if source.kind == "feed":
        from services.rss_pipeline.feeds import collect

        return collect(source, client)
    if source.kind in _BANGUMI_KINDS:
        from services.rss_pipeline.collectors.bangumi import collect

        return collect(source, client)
    if source.kind in _BILIBILI_KINDS:
        from services.rss_pipeline.collectors.bilibili import collect

        return collect(source, client)
    if source.kind in _MIHOYO_KINDS:
        from services.rss_pipeline.collectors.mihoyo import collect

        return collect(source, client)
    if source.kind in _ARKNIGHTS_KINDS:
        from services.rss_pipeline.collectors.arknights import collect

        return collect(source, client)

    # 配置加载时已经验证 kind；这里保护手工构造 ContentSource 的调用。
    raise ValueError(f"Unsupported content source kind: {source.kind}")
