# Moegal Agent

Moegal Agent 是一个面向二次元内容订阅场景的 Telegram 助手。当前版本以 RSS/RSSHub 为内容源，支持关键词订阅、取消订阅、查看订阅，以及通过 `/digest` 手动获取匹配内容摘要。

## 功能

- Telegram Bot 轮询模式运行。
- 通过自然语言或 `/subscribe` 管理关键词订阅。
- 后台定时刷新 `config/rss_feeds.txt` 中配置的 RSSHub 路由。
- 将 RSS 条目缓存到 PostgreSQL，并按用户订阅生成摘要。
- 启动时自动拉起本地 RSSHub 和 Redis Docker 容器。

## 环境要求

- uv
- PostgreSQL
- Docker

## 配置

项目启动时会读取仓库根目录下的 `.env` 文件。最小配置示例：

```env
TELEGRAM_BOT_TOKEN=
DATABASE_URL=postgresql+psycopg://user:password@127.0.0.1:5432/moegal
OPENAI_API_KEY=
MOEGAL_MODEL=

MOEGAL_RSSHUB_BASE_URL=http://127.0.0.1:1200
MOEGAL_RSSHUB_ACCESS_KEY=moegal_rsshub
MOEGAL_RSS_REFRESH_INTERVAL_SECONDS=28800
MOEGAL_RSS_FETCH_CONCURRENCY=8
```

可选配置：

- `OPENAI_BASE_URL`：使用 OpenAI 兼容服务时配置。
- `MOEGAL_RSSHUB_BASE_URL`：RSSHub 访问地址，默认 `http://127.0.0.1:1200`。
- `MOEGAL_RSSHUB_ACCESS_KEY`：RSSHub 访问密钥，默认 `moegal_rsshub`。
- `MOEGAL_RSS_REFRESH_INTERVAL_SECONDS`：RSS 缓存刷新间隔，默认 28800 秒，最小值 3600 秒。
- `MOEGAL_RSS_FETCH_CONCURRENCY`：RSS 源并发抓取数量，默认 8，范围 1 到 32。

## 内容源

RSSHub 路由配置在 `config/rss_feeds.txt`，每行一个路由：

```text
/bangumi.tv/calendar/today
/openai/blog
```

相对路由会基于 `MOEGAL_RSSHUB_BASE_URL` 生成完整 URL，并自动附加 `MOEGAL_RSSHUB_ACCESS_KEY`。

## 启动

安装依赖：

```bash
uv sync
```

确认 PostgreSQL 可用并已创建数据库后，启动 Bot：

```bash
uv run python main.py
```

RSSHub 自动管理使用的本地 Docker 默认值，参考 `rsshub/docker-compose.yml`

## Telegram 命令

- `/start`：启动对话。
- `/help`：查看当前支持的命令。
- `/subscribe 关键词`：订阅关键词。
- `/unsubscribe 关键词`：取消订阅关键词。
- `/newchat`：开启新的对话上下文。
- `/digest`：生成当前用户的订阅摘要。
- `/translate`：提示发送图片，并直接翻译下一张图片。

普通文本会进入 Agent 对话；如果内容表达了订阅、取消订阅、查看订阅或生成摘要等意图，Agent 会调用对应工具完成操作。
普通图片会进入多模态理解；漫画图片会先询问是否翻译，用户表达要翻译后发送翻译图，表达不用翻译则按普通图片回答。
如果先发送 `/translate`，或明确说要翻译图片，下一张图片会直接翻译。

## 当前限制

- 摘要需要用户手动执行 `/digest`，暂未实现主动定时推送。
- 数据库初始化使用 `SQLModel.metadata.create_all`，适合早期开发阶段，不等同于正式迁移系统。
