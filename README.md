# Moegal Agent

## RSS/RSSHub digest

The first subscription version uses RSS/RSSHub feeds and manual `/digest`.

RSSHub endpoint environment variables:

```env
MOEGAL_RSSHUB_BASE_URL=http://127.0.0.1:1200
MOEGAL_RSSHUB_ACCESS_KEY=moegal_rsshub
```

RSS feeds live in `config/rss_feeds.txt`, one route per line:

```text
/bangumi.tv/calendar/today
```

RSSHub is managed automatically when the project starts. The code uses fixed local Docker defaults: `rsshub`, `rsshub-redis`, `rss_default`, `diygod/rsshub:chromium-bundled`, and `redis:alpine`.

Flow:

1. Add a keyword subscription with `/subscribe xxx` or natural language.
2. Run `/digest`.
3. The bot fetches configured feeds, stores RSS entries, matches active keyword subscriptions, returns pending items, then marks them as sent after the Telegram reply succeeds.
