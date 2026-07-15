# Moegal Agent

Moegal Agent 是一个面向二次元内容订阅场景的 Telegram/QQ 助手。当前版本以 RSS/RSSHub 为内容源，支持关键词订阅、取消订阅、查看订阅，以及通过 `/digest` 手动获取匹配内容摘要。

## 功能

- Telegram Bot 轮询模式运行，QQ Bot 使用 botpy C2C 事件。
- 通过自然语言或 `/subscribe` 管理关键词订阅。
- 支持普通图片理解、漫画图片翻译询问，以及 `/translate` 后直接翻译下一张图片。
- 后台定时刷新 `config/rss_feeds.txt` 中配置的 RSSHub 路由。
- 将 RSS 条目缓存到 PostgreSQL，并按用户订阅生成摘要。
- 启动时自动拉起本地 RSSHub 和 Redis Docker 容器。

## 环境要求

- uv
- PostgreSQL
- Docker

## 文档

- [记忆系统实现说明](doc/memory-system.md)

## 配置

项目启动时会读取仓库根目录下的 `.env` 文件。最小配置示例：

```env
TELEGRAM_BOT_TOKEN=
DATABASE_URL=postgresql+psycopg://user:password@127.0.0.1:5432/moegal
OPENAI_API_KEY=
MOEGAL_MODEL=
OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
MOEGAL_LLM_GATEWAY_BASE_URL=http://127.0.0.1:9426/v1

MOEGAL_RSSHUB_BASE_URL=http://127.0.0.1:1200
MOEGAL_RSSHUB_ACCESS_KEY=moegal_rsshub
MOEGAL_RSS_REFRESH_INTERVAL_SECONDS=28800
MOEGAL_RSS_FETCH_CONCURRENCY=8

QQ_BOT_APPID=
QQ_BOT_SK=
```

可选配置：

- `OPENAI_BASE_URL`：上游 OpenAI 兼容服务地址。启动 Go gateway 时，gateway 会用它转发请求。
- `MOEGAL_LLM_GATEWAY_BASE_URL`：Python 侧连接本地 Go gateway 的地址；未配置时 Python 会直接使用 `OPENAI_BASE_URL`。
- `MOEGAL_RSSHUB_BASE_URL`：RSSHub 访问地址，默认 `http://127.0.0.1:1200`。
- `MOEGAL_RSSHUB_ACCESS_KEY`：RSSHub 访问密钥，默认 `moegal_rsshub`。
- `MOEGAL_RSS_REFRESH_INTERVAL_SECONDS`：RSS 缓存刷新间隔，默认 28800 秒，最小值 3600 秒。
- `MOEGAL_RSS_FETCH_CONCURRENCY`：RSS 源并发抓取数量，默认 8，范围 1 到 32。
- `MOEGAL_MAX_LINKED_BOT_USERS_PER_PLATFORM`：每个 Web 用户同平台最多可绑定的 Bot 账号数，默认 `2`。
- `MOEGAL_CONTEXT_MAX_TOKENS`：模型热路径保留的最近会话 token 预算，默认 `12000`。
- `MOEGAL_MEMORY_CONSOLIDATION_MESSAGES`：触发后台记忆巩固的新消息数，默认 `12`，范围 4 到 100。
- `MOEGAL_PUBLIC_ASSET_BASE_URL`：QQ 图片回图必需。翻译后图片的公开静态资源地址，例如 `https://static.example.com/moegal-qq`。
- `MOEGAL_QQ_IMAGE_REMOTE_HOST`：QQ 图片回图必需。SFTP 上传目标主机。
- `MOEGAL_QQ_IMAGE_REMOTE_PORT`：远端 SSH 端口，默认 `22`。
- `MOEGAL_QQ_IMAGE_REMOTE_USER`：QQ 图片回图必需。远端 SSH 用户。
- `MOEGAL_QQ_IMAGE_REMOTE_KEY_FILE`：推荐配置。远端 SSH 私钥路径，优先用于 SFTP 上传。
- `MOEGAL_QQ_IMAGE_REMOTE_PASSWORD`：未配置私钥时使用的远端 SSH 密码。不建议提交或写入版本库。
- `MOEGAL_QQ_IMAGE_REMOTE_DIR`：QQ 图片回图必需。远端 nginx 静态目录，例如 `/path/to/nginx/html/moegal-qq/image`。

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

如果要通过 Go gateway 转发 LLM 请求，可以用脚本同时启动 gateway、FastAPI Web API 和 Python Bot：

```bash
./scripts/start_with_gateway.sh
```

脚本会读取 `.env`、后台启动本地 gateway 和 FastAPI，再启动 Python Bot。Python 是否连接
gateway 由 `.env` 中的 `MOEGAL_LLM_GATEWAY_BASE_URL` 决定。FastAPI 默认监听
`127.0.0.1:8000`，可以用 `MOEGAL_WEB_HOST`、`MOEGAL_WEB_PORT` 覆盖；设置
`MOEGAL_WEB_RELOAD=1` 可启用 uvicorn reload。传给脚本的参数会原样传给 `main.py`，例如：

```bash
./scripts/start_with_gateway.sh --bot qq
./scripts/start_with_gateway.sh --bot qq,tg
```

默认会同时启动 QQ 和 Telegram。也可以通过 `--bot` 指定要启动的机器人：

```bash
uv run python main.py --bot qq
uv run python main.py --bot qq,tg
```

RSSHub 自动管理使用的本地 Docker 默认值，参考 `rsshub/docker-compose.yml`

## Web API

前端只读接口由 FastAPI 提供，入口在 `web/` 包。如果不使用
`scripts/start_with_gateway.sh`，也可以单独启动 Web API：

```bash
uv run uvicorn web.app:app --reload
```

Web 端聊天机器人使用独立的简单账号体系：

- `POST /api/auth/register`：注册 Web 用户，参数为 `username` 和 `password`。平台会分配 10 位纯数字用户 ID。
- `POST /api/auth/login`：使用 10 位用户 ID 和密码登录并返回 bearer token。
- `GET /api/auth/me`：读取当前 Web 用户。
- `POST /api/admin/link-codes`：登录后申请通用绑定码，绑定码 10 分钟有效。
- `GET /api/admin/bindings`：读取当前 Web 账号和已经绑定的 TG/QQ 账号。
- `GET /api/subscriptions?platform=web&platform_user_id=1000000000`：返回当前 Web 用户启用中的订阅。
- `GET /api/subscriptions?platform=tg&platform_user_id=42`：登录且绑定对应 Bot 账号后，返回 Bot 用户启用中的订阅。
- `GET /api/chat-history?platform=web&platform_user_id=1000000000`：返回当前 Web 用户会话和消息记录。
- `GET /api/chat-history?platform=tg&platform_user_id=42`：登录且绑定对应 Bot 账号后，返回 Bot 用户会话和消息记录。
- `POST /api/web-chat/messages`：发送 Web 聊天消息。
- `POST /api/web-chat/messages/stream`：发送 Web 聊天消息，并通过 SSE 流式返回助手回复。
- `GET /api/web-chat/history`：读取当前 Web 用户的聊天记录。
- `POST /api/web-chat/new`：开启新的 Web 聊天上下文。
- `GET /api/web-chat/memories`：查看当前 Web 用户的有效长期记忆。
- `PATCH/DELETE /api/web-chat/memories/{id}`：纠正或删除一条长期记忆。
- `DELETE /api/web-chat/memories`：清空全部长期记忆，但保留聊天历史。
- `GET/PATCH /api/web-chat/memory-settings`：读取或修改记忆、自动整理和历史引用开关。

Web 消息请求可以传入 `temporary=true` 和客户端生成的 `temporary_thread_id` 开启临时聊天。临时聊天只在进程内保持当前会话连续性，不读取长期记忆，也不会写入 `conversations`、`messages` 或 PostgreSQL checkpoint。

绑定流程：Web 用户在 `/admin` 申请绑定码，然后在 Telegram 或 QQ bot 内发送
`/link 绑定码`。绑定成功后，管理后台可以查看当前 Web 账号和已绑定 Bot 账号的订阅和聊天历史。
暂不提供解绑功能。

## Frontend

前端位于 `web/frontend/`，使用 React、Vite、Tailwind CSS 和 shadcn/ui 风格组件。启动方式：

```bash
cd web/frontend
npm install
npm run dev
```

本地联调时先启动 FastAPI，或直接使用 `./scripts/start_with_gateway.sh`。前端开发服务会把
`/api` 代理到 `http://127.0.0.1:8000`，也可以通过 `VITE_API_BASE_URL` 指定后端地址。

前端根路径 `/` 是 Web 聊天页，`/admin` 是需要 Web 登录的管理后台。Web 账号数据默认可查看；
TG/QQ 数据必须先完成 `/link` 绑定后才能查看。

## QQ 图片回图配置

QQ 发送图片需要一个 QQ 服务器可访问的公网 URL。当前使用远程上传方式：本地 bot 生成图片，通过 SFTP 上传到云服务器 nginx 静态目录，然后把公网 URL 发给 QQ。推荐配置如下：

```env
MOEGAL_PUBLIC_ASSET_BASE_URL=https://static.example.com/moegal-qq
MOEGAL_QQ_IMAGE_REMOTE_HOST=example.com
MOEGAL_QQ_IMAGE_REMOTE_PORT=22
MOEGAL_QQ_IMAGE_REMOTE_USER=deploy
MOEGAL_QQ_IMAGE_REMOTE_KEY_FILE=/absolute/path/to/.secrets/moegal_qq_image_upload
MOEGAL_QQ_IMAGE_REMOTE_DIR=/path/to/nginx/html/moegal-qq/image
```

本地需要准备 SSH key：

```bash
mkdir -p .secrets
ssh-keygen -t ed25519 -N '' -f .secrets/moegal_qq_image_upload -C moegal-qq-image-upload
chmod 600 .secrets/moegal_qq_image_upload
```

把 `.secrets/moegal_qq_image_upload.pub` 的内容追加到云服务器对应用户的 `~/.ssh/authorized_keys`。服务器侧目录准备：

```bash
mkdir -p /path/to/nginx/html/moegal-qq/image
chmod 755 /path/to/nginx/html/moegal-qq /path/to/nginx/html/moegal-qq/image
```

需要确保 nginx 或其他静态服务能把该目录暴露到 `MOEGAL_PUBLIC_ASSET_BASE_URL` 下。公网最终应能访问：

```text
https://static.example.com/moegal-qq/image/<文件名>
```

验证上传链路：

```bash
ssh -i .secrets/moegal_qq_image_upload -o BatchMode=yes deploy@example.com 'echo key-ok'

set -a; source .env; set +a
uv run python - <<'PY'
from bots.qq.app import _save_public_translated_image
from services.image_workflow import TranslatedImage
url = _save_public_translated_image(
    TranslatedImage(file_bytes=b'upload ok\n', file_name='upload-test.txt')
)
print(url)
PY

curl -fsS https://static.example.com/moegal-qq/image/upload-test.txt
ssh -i .secrets/moegal_qq_image_upload deploy@example.com \
  'rm -f /path/to/nginx/html/moegal-qq/image/upload-test.txt'
```

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
如果先发送 `/translate`，下一张图片会直接翻译；如果发送图片时说明要翻译，也会直接翻译当前图片。

## 对话持久化

普通文本对话上下文通过 LangGraph PostgreSQL checkpoint 保存到 `DATABASE_URL` 指向的数据库中，进程重启后会继续使用当前活跃会话的上下文。
`conversations` 表保存每个平台用户的会话版本和当前活跃会话；`thread_id` 使用随机 UUID，并作为 LangGraph checkpoint 的会话隔离键。
`messages` 表保存用户输入和最终助手回复，方便后续查询聊天记录。
执行 `/newchat` 会在当前活跃会话已有消息时结束旧版本并创建新版本；如果当前已经是空新对话，则只提示已在新对话中，不会额外创建空记录。

模型热路径会按 `MOEGAL_CONTEXT_MAX_TOKENS`（默认 `12000`）裁剪较早消息，数据库 checkpoint 仍保留完整会话。
长期记忆根据本轮消息，从有效记忆中使用 namespace、数据库关键词/全文候选和应用层相关性混合召回，综合重要度、置信度和新鲜度排序，默认召回最多 6 条，并限制为约 1600 字符的 JSON 上下文。
`user_memories` 保存语义记忆的来源、置信度、重要度、过期时间和访问统计；`memory_revisions` 保存创建、更新、恢复及遗忘轨迹。
每累计 `MOEGAL_MEMORY_CONSOLIDATION_MESSAGES` 条新消息会后台生成滚动摘要，并在 `/newchat` 时强制收尾。`conversation_memories` 保存平台隔离的情景摘要、主题和未完成事项；巩固器会把稳定用户事实写回全局语义记忆，并再次过滤敏感信息。
`user_memory_settings` 保存用户的记忆启用、自动整理和历史引用开关。Web 聊天页提供记忆查看、纠正、删除、清空和临时聊天入口。

可以运行轻量检索评测：

```bash
uv run python -m scripts.evaluate_memory_retrieval
```

## QQ C2C

- 普通文本会进入 Agent 对话。
- `/newchat`：开启新的对话上下文。
- `/translate`：提示发送图片，并直接翻译下一张图片。
- 普通图片会进入多模态理解。
- 漫画图片会先询问是否翻译；用户表达要翻译后发送翻译图，表达不用翻译则按普通图片回答。

QQ 侧当前只接入 C2C 图片处理；多附件消息只处理第一张图片。漫画翻译 pending 状态保存在进程内存中，进程重启后会丢失。

## 当前限制

- 摘要需要用户手动执行 `/digest`，暂未实现主动定时推送。
- 数据库初始化使用 `SQLModel.metadata.create_all`，适合早期开发阶段，不等同于正式迁移系统。
