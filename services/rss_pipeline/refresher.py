import os
import threading
from dataclasses import dataclass

from utils.logger import logger
from services.rss_pipeline.content_store import upsert_rss_entries
from services.rss_pipeline.feeds import fetch_rss_entries, get_configured_feed_urls


DEFAULT_RSS_REFRESH_INTERVAL_SECONDS = 60 * 60 * 8
MIN_RSS_REFRESH_INTERVAL_SECONDS = 60 * 60
RSS_REFRESH_INTERVAL_ENV = "MOEGAL_RSS_REFRESH_INTERVAL_SECONDS"


@dataclass(frozen=True)
class RssCacheRefreshResult:
    feed_count: int
    entry_count: int
    error_count: int
    created_count: int = 0
    updated_count: int = 0


@dataclass(frozen=True)
class RssCacheRefresher:
    thread: threading.Thread
    stop_event: threading.Event
    interval_seconds: int

    def stop(self, timeout: float | None = 10.0) -> None:
        self.stop_event.set()
        self.thread.join(timeout=timeout)
        if self.thread.is_alive():
            if timeout is None:
                logger.warning("RSS cache refresher did not stop.")
            else:
                logger.warning("RSS cache refresher did not stop within %.1f seconds.", timeout)


def get_rss_refresh_interval_seconds() -> int:
    raw_value = os.getenv(RSS_REFRESH_INTERVAL_ENV)
    if raw_value is None or raw_value.strip() == "":
        return DEFAULT_RSS_REFRESH_INTERVAL_SECONDS

    try:
        interval_seconds = int(raw_value)
    except ValueError:
        logger.warning(
            "Invalid %s=%r; using default %s seconds.",
            RSS_REFRESH_INTERVAL_ENV,
            raw_value,
            DEFAULT_RSS_REFRESH_INTERVAL_SECONDS,
        )
        return DEFAULT_RSS_REFRESH_INTERVAL_SECONDS

    if interval_seconds < MIN_RSS_REFRESH_INTERVAL_SECONDS:
        logger.warning(
            "%s=%s is below the minimum; using %s seconds.",
            RSS_REFRESH_INTERVAL_ENV,
            interval_seconds,
            MIN_RSS_REFRESH_INTERVAL_SECONDS,
        )
        return MIN_RSS_REFRESH_INTERVAL_SECONDS

    return interval_seconds


def refresh_rss_cache_once() -> RssCacheRefreshResult:
    feed_urls = get_configured_feed_urls()
    if not feed_urls:
        logger.info("RSS cache refresh skipped: no configured feed URLs.")
        return RssCacheRefreshResult(feed_count=0, entry_count=0, error_count=0)

    fetch_result = fetch_rss_entries(feed_urls)
    created_count = 0
    updated_count = 0

    if fetch_result.entries:
        # 如果抓到了 RSS 条目，就把它们写入存储
        upsert_result = upsert_rss_entries(fetch_result.entries)
        created_count = upsert_result.created_count
        updated_count = upsert_result.updated_count

    result = RssCacheRefreshResult(
        feed_count=len(feed_urls),
        entry_count=len(fetch_result.entries),
        error_count=len(fetch_result.errors),
        created_count=created_count,
        updated_count=updated_count,
    )
    logger.info(
        "RSS cache refreshed: feeds=%s entries=%s errors=%s created=%s updated=%s",
        result.feed_count,
        result.entry_count,
        result.error_count,
        result.created_count,
        result.updated_count,
    )
    return result


def start_rss_cache_refresher(
    interval_seconds: int | None = None,
) -> RssCacheRefresher:
    resolved_interval = (
        interval_seconds
        if interval_seconds is not None
        else get_rss_refresh_interval_seconds()
    )
    stop_event = threading.Event()
    thread = threading.Thread(
        target=_run_refresh_loop,
        args=(stop_event, resolved_interval),
        name="rss-cache-refresher",
        daemon=True,
    )
    thread.start()
    logger.info(
        "RSS cache refresher started with interval=%s seconds.",
        resolved_interval,
    )
    return RssCacheRefresher(
        thread=thread,
        stop_event=stop_event,
        interval_seconds=resolved_interval,
    )


def _run_refresh_loop(stop_event: threading.Event, interval_seconds: int) -> None:
    while not stop_event.is_set():
        # 只要没有收到停止信号，就一直循环
        try:
            refresh_rss_cache_once()
        except Exception:
            logger.exception("RSS cache refresh failed.")

        # 等待 interval_seconds 秒；如果等待期间收到了停止信号，就跳出循环
        if stop_event.wait(interval_seconds):
            # False 代表等满了 interval_seconds 秒，期间没有调用 stop_event.set()
            break
