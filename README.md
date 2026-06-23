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

如果要通过 Go gateway 转发 LLM 请求，可以用脚本同时启动 gateway 和 Python 项目：

```bash
./scripts/start_with_gateway.sh
```

脚本只负责读取 `.env`、后台启动本地 gateway、再启动 Python 项目。Python 是否连接
gateway 由 `.env` 中的 `MOEGAL_LLM_GATEWAY_BASE_URL` 决定。传给脚本的参数会原样传给
`main.py`，例如：

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
执行 `/newchat` 会结束当前活跃会话并创建新的会话版本，不会删除旧聊天记录，也不会影响订阅和摘要记录。

## QQ C2C

- 普通文本会进入 Agent 对话。
- `/translate`：提示发送图片，并直接翻译下一张图片。
- 普通图片会进入多模态理解。
- 漫画图片会先询问是否翻译；用户表达要翻译后发送翻译图，表达不用翻译则按普通图片回答。

QQ 侧当前只接入 C2C 图片处理；多附件消息只处理第一张图片。漫画翻译 pending 状态保存在进程内存中，进程重启后会丢失。

## 当前限制

- 摘要需要用户手动执行 `/digest`，暂未实现主动定时推送。
- 数据库初始化使用 `SQLModel.metadata.create_all`，适合早期开发阶段，不等同于正式迁移系统。
