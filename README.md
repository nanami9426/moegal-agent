# Moegal Agent

## RSS/RSSHub digest

The first subscription version uses RSS/RSSHub feeds and manual `/digest`.

RSSHub endpoint environment variables:

```env
MOEGAL_RSSHUB_BASE_URL=http://127.0.0.1:1200
MOEGAL_RSSHUB_ACCESS_KEY=moegal_rsshub
MOEGAL_RSS_REFRESH_INTERVAL_SECONDS=1800
```

`MOEGAL_RSS_REFRESH_INTERVAL_SECONDS` controls the background cache refresh interval.
It defaults to 1800 seconds and is clamped to a minimum of 60 seconds.

RSS feeds live in `config/rss_feeds.txt`, one route per line:

```text
/bangumi.tv/calendar/today
```

RSSHub is managed automatically when the project starts. The code uses fixed local Docker defaults: `rsshub`, `rsshub-redis`, `rss_default`, `diygod/rsshub:chromium-bundled`, and `redis:alpine`.

Flow:

1. Add a keyword subscription with `/subscribe xxx` or natural language.
2. The bot refreshes configured RSS feeds in the background and stores entries in `content_items`.
3. Run `/digest`.
4. The bot reads cached RSS entries, matches active keyword subscriptions, returns pending items, then marks them as sent after the Telegram reply succeeds.
