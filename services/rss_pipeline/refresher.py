import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from utils.logger import logger
from services.rss_pipeline.content_store import upsert_rss_entries
from services.rss_pipeline.feeds import fetch_rss_entries, get_configured_feed_urls


DEFAULT_RSS_REFRESH_INTERVAL_SECONDS = 60 * 60 * 8
MIN_RSS_REFRESH_INTERVAL_SECONDS = 60 * 60
RSS_REFRESH_INTERVAL_ENV = "MOEGAL_RSS_REFRESH_INTERVAL_SECONDS"
RSS_LAST_REFRESH_AT_PATH = Path("temp/rss_last_refresh_at")


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
        args=(stop_event, resolved_interval, RSS_LAST_REFRESH_AT_PATH),
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


def _run_refresh_loop(stop_event: threading.Event, interval_seconds: int, last_refresh_at_path: Path) -> None:
    while not stop_event.is_set():
        # 只要没收到信号就一直循环
        # 计算还有多久刷新
        wait_seconds = _seconds_until_next_refresh(
            now=time.time(),
            last_refresh_at=_read_last_refresh_at(last_refresh_at_path),
            interval_seconds=interval_seconds,
        )
        if wait_seconds > 0:
            logger.info(
                "RSS cache refresh skipped: waiting %.1f seconds until refresh interval elapses.",
                wait_seconds,
            )
            if stop_event.wait(wait_seconds):
                break
            continue

        try:
            result = refresh_rss_cache_once()
        except Exception:
            logger.exception("RSS cache refresh failed.")
            if stop_event.wait(interval_seconds):
                break
            continue

        if result.feed_count > 0:
            refreshed_at = time.time()
            if _write_last_refresh_at(last_refresh_at_path, refreshed_at):
                logger.info(
                    "RSS cache refresh timestamp written to %s.",
                    last_refresh_at_path,
                )

        if stop_event.wait(interval_seconds):
            break


def _read_last_refresh_at(path: Path) -> float | None:
    try:
        raw_value = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    except OSError:
        logger.exception("Failed to read RSS cache refresh timestamp from %s.", path)
        return None

    if not raw_value:
        return None

    try:
        return float(raw_value)
    except ValueError:
        logger.warning(
            "Invalid RSS cache refresh timestamp in %s: %r.",
            path,
            raw_value,
        )
        return None


def _write_last_refresh_at(path: Path, refreshed_at: float) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{refreshed_at:.6f}\n", encoding="utf-8")
    except OSError:
        logger.exception("Failed to write RSS cache refresh timestamp to %s.", path)
        return False

    return True


def _seconds_until_next_refresh(
    *,
    now: float,
    last_refresh_at: float | None,
    interval_seconds: int,
) -> float:
    if last_refresh_at is None or last_refresh_at > now:
        return 0

    elapsed_seconds = now - last_refresh_at
    if elapsed_seconds >= interval_seconds:
        return 0

    return interval_seconds - elapsed_seconds
