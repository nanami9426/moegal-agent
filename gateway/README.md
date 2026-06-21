## Moegal Agent 内部网关

默认启动在 `:9426`。

当前功能：

- `GET /healthz`：健康检查。
- `/v1/*`：OpenAI-compatible LLM 请求透传到上游服务。

## 配置

gateway 需要配置上游 OpenAI-compatible API 地址：

```env
OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
```

`OPENAI_BASE_URL` 建议包含 `/v1` 或兼容服务的等价路径。gateway 暴露的
`/v1/chat/completions` 会转发到 `<OPENAI_BASE_URL>/chat/completions`。

当前最小版本采用客户端鉴权透传：gateway 不注入、不替换 API key，调用方传入的
`Authorization` header 会原样转发给上游。

Python 侧不需要改代码，只需要在 `.env` 中配置 gateway 地址：

```env
MOEGAL_LLM_GATEWAY_BASE_URL=http://127.0.0.1:9426/v1
OPENAI_API_KEY=<真实上游 key>
MOEGAL_MODEL=<模型名>
```

如果用项目根目录的 `scripts/start_with_gateway.sh` 启动，脚本只负责同时启动 gateway
和 Python 项目；Python 是否连接 gateway 由 `MOEGAL_LLM_GATEWAY_BASE_URL` 控制。

## 启动

```bash
cd gateway
go run .
```

QQ 翻译图当前通过 Python 侧 SFTP 直接上传到云服务器 nginx 静态目录，不依赖本地 gateway。
