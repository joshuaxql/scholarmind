# 开发指南

## 前置条件

- Python 3.11 或 3.12
- Node.js 22 或更高版本
- npm

ScholarMind 的默认开发拓扑全部运行在本机进程内：SQLite、inline job、本地对象目录和数据库向量检索。模型接口之外不需要启动其他服务。

## 一键安装与启动

从仓库根目录运行：

```bash
python scripts/setup.py
```

该脚本：

1. 创建 `.venv`；
2. 安装 `apps/api[dev]`；
3. 在 `apps/web` 执行 `npm ci`；
4. 缺少 `.env` 时从 `.env.example` 创建。

编辑 `.env` 后启动：

```bash
python scripts/start.py --reload
```

启动器从根目录加载 `.env`、执行 `alembic upgrade head`，再启动 API `127.0.0.1:8000` 与 Web `localhost:3000`。`Ctrl+C` 会终止两个进程。

常用模式：

```bash
python scripts/start.py --api-only --reload
python scripts/start.py --web-only
python scripts/start.py --production
```

`--production` 只表示先构建并运行 Next.js production server；API 的安全环境仍由 `.env` 中的 `ENVIRONMENT` 控制。

## 可视化配置

启动后点击侧栏底部的齿轮，或打开 `/settings`。设置页包含后端配置和启动器的 `WEB_HOST`、`WEB_PORT`、`API_INTERNAL_URL`、`API_INTERNAL_BEARER_TOKEN`，共 55 项，覆盖 `.env.example` 中的全部参数；尚未写入文件的项显示默认值。可按模型、检索、摄取、存储、鉴权和网络分组编辑，也可按中文名称或环境变量名搜索。

- 页面显示根目录 `.env` 的文件配置，保存仅更新改动的字段，保留注释和未识别的配置行。已有进程和启动终端的同名环境变量不会被改写；启动终端中的环境变量仍优先于文件。
- 已有密钥和含凭据的连接字符串不会返回浏览器。密码输入框留空表示保留；输入新值表示替换；点击“清除”后保存才会清空。新输入的凭据仅用于本次请求，不写入浏览器存储。
- 保存前校验类型、范围、模型三元组、鉴权及生产环境约束。文件已被其他操作修改时返回冲突，页面保留草稿，允许明确放弃修改后重新读取。
- 保存使用同目录临时文件和原子替换。文件不可写时返回错误，原文件保持不变。输入采用单行字面量，不支持 `${...}` 展开；`CORS_ORIGINS` 填写 JSON 数组。启动器使用相同的 dotenv 转义规则读取引号、反斜杠和行尾注释。
- 所有修改都需要重启：在启动终端按 `Ctrl+C`，再执行原启动命令，例如 `python scripts/start.py --production` 或 `python scripts/start.py --reload`。仅刷新网页不会重建模型、数据库或存储客户端；独立运行的 worker 也应重启。
- 修改 API/前端端口时同步检查 `API_INTERNAL_URL`、`WEB_ORIGIN` 和 `CORS_ORIGINS`。更换数据库或文件目录不会迁移数据；更换嵌入模型不会自动重建已有论文索引。

设置编辑器仅用于本机：API 和 Web 的监听地址均须为 `localhost`、`127.0.0.1` 或 `::1`，浏览器也需通过回环地址访问。BFF 检查同源请求标记和真实 Host/Origin，后端检查回环连接与既有 Bearer 鉴权。绑定到公网地址或从远程域名访问时，配置编辑不可用；部署环境仍通过服务器上的 `.env` 管理。

## OpenAI 兼容模型配置

生成与嵌入分别使用独立三元组：

```dotenv
LLM_BASE_URL=https://provider.example/v1
LLM_API_KEY=your-chat-key
LLM_MODEL=your-chat-model

EMBEDDING_BASE_URL=https://embedding-provider.example/v1
EMBEDDING_API_KEY=your-embedding-key
EMBEDDING_MODEL=your-embedding-model
```

应用发出的请求为：

```text
POST {LLM_BASE_URL}/chat/completions
Authorization: Bearer {LLM_API_KEY}
Content-Type: application/json

POST {EMBEDDING_BASE_URL}/embeddings
Authorization: Bearer {EMBEDDING_API_KEY}
Content-Type: application/json
```

因此 OpenAI 官方地址应填写为 `https://api.openai.com/v1`，而不是完整的 `/chat/completions` 或 `/embeddings` 地址。兼容服务可以使用 `http://127.0.0.1:<port>/v1`；即使本地服务不校验凭据，也需提供一个非空占位 Key。

LLM 请求使用标准 `messages`、`model`、`stream=true`、`temperature` 和 `max_tokens` 字段，并解析 `data: {"choices":[{"delta":{"content":...}}]}` 与 `data: [DONE]`。嵌入请求使用 `{"model": ..., "input": [...]}`，按响应 `data[].index` 恢复顺序并自动推断维度。

三个值必须同时配置；三者全部为空时分别回退到 `LocalGroundedGateway` 和 `LocalHashEmbedding`。

## 本地数据与向量

默认目录：

```text
data/
  scholarmind.db       SQLite 状态、分块、会话和 embedding JSON
  objects/papers/...   PDF 与 Markdown
```

摄取阶段通过 `/embeddings` 生成每个 chunk 的向量，并与 `embedding_model` 标识一起事务写入 `paper_chunks`。查询阶段只读取当前 `paper_id`，采用 75% cosine + 25% 词法评分；嵌入查询暂时失败时降级为论文内词法检索。

修改嵌入服务或模型后，旧 chunk 的模型标识不会匹配新配置，系统会安全降级到词法检索。开发阶段可删除 `data/` 后重新提交论文以完整重建向量。

## 手工启动

不使用统一启动器时，先从根目录迁移并启动 API：

```bash
.venv/bin/python -m alembic -c apps/api/alembic.ini upgrade head
.venv/bin/python -m uvicorn scholarmind.main:app --app-dir apps/api --reload --port 8000
```

另一个终端启动 Web：

```bash
npm --prefix apps/web run dev
```

Windows 将 `.venv/bin/python` 替换为 `.venv\Scripts\python.exe`。手工启动时还需确保 Web 进程能够读取 `API_INTERNAL_URL`；默认值已经指向 `http://127.0.0.1:8000`。

## 数据库迁移

```bash
.venv/bin/python -m alembic -c apps/api/alembic.ini upgrade head
.venv/bin/python -m alembic -c apps/api/alembic.ini current
.venv/bin/python -m alembic -c apps/api/alembic.ini check
```

创建迁移：

```bash
.venv/bin/python -m alembic -c apps/api/alembic.ini revision --autogenerate -m "describe change"
```

提交前检查生成 SQL、约束、降级路径，并同时验证全新数据库升级和现有数据库增量升级。

## 测试与静态检查

```bash
make lint
make test
make build
```

等价的后端命令：

```bash
cd apps/api
../../.venv/bin/ruff check scholarmind tests
../../.venv/bin/ruff format --check scholarmind tests
../../.venv/bin/mypy scholarmind
../../.venv/bin/pytest
```

前端命令：

```bash
npm --prefix apps/web run lint
npm --prefix apps/web run typecheck
npm --prefix apps/web test
npm --prefix apps/web run build
```

后端覆盖率门槛为 70%。测试覆盖 SSRF、对象路径、幂等、状态机、OpenAI 协议、数据库/Qdrant 论文隔离、SSE、引用和数据保留。

## API 快速参考

所有业务路由位于 `/api/v1`；当 `AUTH_REQUIRED=true` 时需要：

```http
Authorization: Bearer <API_BEARER_TOKEN>
```

| 方法 | 路由 | 用途 |
|---|---|---|
| GET | `/settings` | 本机读取 `.env` 配置目录与脱敏值 |
| POST | `/settings` | 携带 `revision` 与 `updates` 原子更新本机配置 |
| POST | `/papers` | 提交 `{ "arxiv": "2501.06713" }` |
| GET | `/papers` | 分页列表 |
| GET | `/papers/{id}` | 状态和最新任务 |
| POST | `/papers/{id}/retry` | 重试 FAILED 或修复未入队 QUEUED job |
| GET | `/papers/{id}/pdf` | 授权读取 PDF |
| POST | `/papers/{id}/chat/stream` | SSE 问答 |
| GET | `/papers/{id}/conversations` | 当前论文的历史会话列表与消息 |
| GET | `/papers/{id}/conversations/{conversation_id}` | 恢复指定会话消息 |
| DELETE | `/papers/{id}/conversations/{conversation_id}` | 删除所属论文下的会话及消息 |
| DELETE | `/papers/{id}/history` | 从最近阅读中移除，保留论文内容和会话 |
| POST | `/research/search` | 按主题、分类和日期检索 arXiv 摘要 |
| GET | `/research`、`/research/{id}` | 调研历史与结果快照 |
| DELETE | `/research/{id}` | 删除调研记录、结果快照和报告 |
| POST | `/research/{id}/analyze/stream` | SSE 生成领域进展与瓶颈报告 |

单篇问答 SSE 事件依次为 `meta`、多个 `token`、`done`；领域分析返回 `meta`、`done`。流开始后的失败均使用 `error`。
