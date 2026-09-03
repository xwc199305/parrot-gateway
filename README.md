# Parrot Gateway

一个面向 OpenAI 协议的 Python AI Gateway。第一阶段提供一个稳定的
`/v1/chat/completions` 入口，并将请求转发给任意 OpenAI-compatible 上游。

## 技术栈

- Python 3.13、uv
- FastAPI、Pydantic v2、httpx
- pytest、Ruff

## 工程结构

```text
src/parrot_gateway/
├── core/             # 配置与基础设施
├── domain/           # OpenAI 协议模型与领域错误
├── providers/        # ProviderAdaptor 与各厂商实现
│   ├── base.py
│   ├── openai.py
│   └── deepseek.py
├── services/
│   └── model_router.py # 按模型名前缀路由
└── main.py           # FastAPI 应用入口
```

## 快速开始

```bash
cp .env.example .env
# 编辑 .env，填写 UPSTREAM_API_KEY（或替换 UPSTREAM_BASE_URL）
uv sync --all-groups
uv run uvicorn parrot_gateway.main:app --reload
```

调用网关：

```bash
curl http://127.0.0.1:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"gpt-4.1-mini","messages":[{"role":"user","content":"Hello"}]}'
```

设置 `GATEWAY_API_KEY` 后，客户端还必须提交 `Authorization: Bearer <key>`。

## 当前范围

- OpenAI Chat Completions：普通 JSON 和 SSE 流式响应。
- `ProviderAdaptor` 抽象类隔离路由与厂商适配；`IRChatRequest` 直接对齐
  OpenAI Chat Completions 协议，再由 `OpenAIAdaptor` 或 `DeepseekAdaptor`
  分别负责 `get_endpoint`、`build_request` 和 `parse_response`。
- `ModelRouter` 按模型名前缀分发：`deepseek-` 使用 DeepSeek，`gpt-`、
  `o1-`、`o3-` 和 `chatgpt-` 使用 OpenAI；匹配采用最长前缀优先。
- 网关鉴权支持 `static` 和 `database` 两种模式。`static` 适合本地测试；
  `database` 使用 PostgreSQL 保存网关 Key 的 HMAC hash、状态、过期时间和租户信息。
- 上游错误以原状态码和错误体透传；连接失败会返回 `502`。

Provider API Key 始终只在服务端配置中读取，客户端提交的网关 Key 不会被转发给
外部 Provider。数据库模式需要先创建 `gateway_api_keys` 表并写入 Key hash。
