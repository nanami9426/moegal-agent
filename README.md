# Moegal Agent

## RSS/RSSHub digest

The first subscription version uses RSS/RSSHub feeds and manual `/digest`.

Required environment variable:

```env
MOEGAL_RSS_FEEDS=https://example.com/feed.xml,https://rsshub.app/example
```

Optional environment variables:

```env
MOEGAL_DIGEST_LOOKBACK_HOURS=48
MOEGAL_DIGEST_MAX_ITEMS=10
```

Flow:

1. Add a keyword subscription with `/subscribe xxx` or natural language.
2. Run `/digest`.
3. The bot fetches configured feeds, stores RSS entries, matches active keyword subscriptions, returns pending items, then marks them as sent after the Telegram reply succeeds.
