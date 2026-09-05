# 仓库协作指南

本文件适用于整个 ScholarMind 仓库。默认使用中文沟通和说明变更；代码标识符、命令及已有协议字段沿用英文。开始工作前查看 `git status --short`，保留已有未提交改动，只修改任务涉及的文件。

## 项目概况与目录

ScholarMind 是面向 arXiv 论文精读的本机 RAG 应用，支持论文摄取、带页码引用的流式问答、历史会话、领域摘要检索和中英双语界面。

- `apps/api/scholarmind/`：Python 3.11/3.12、FastAPI、SQLAlchemy 2 后端。
  - `api/routes/` 与 `api/schemas.py`：HTTP 路由、请求与响应契约。
  - `domain/`：领域类型、状态与校验；`services/`：业务流程和外部服务适配。
  - `repositories/`：数据库访问；`db/`：ORM 模型与会话。
  - `core/`：配置、鉴权、日志、限流等；`workers/`：摄取任务与可选 ARQ worker。
- `apps/api/alembic/`：数据库迁移；`apps/api/tests/`：Pytest 测试。
- `apps/web/src/`：Next.js 16 App Router、React 19、严格 TypeScript 前端。
  - `app/`：页面和同源 BFF；`components/`：业务组件；`hooks/`：状态与交互逻辑。
  - `lib/api.ts`、`lib/sse.ts`、`types/api.ts`：API 客户端、SSE 解析及类型契约。
  - `components/i18n/`：语言上下文；前端测试与源码相邻，命名为 `*.test.ts(x)`。
- `scripts/`：跨平台安装与启动；`docs/`：架构、开发、部署、安全和运维文档。
- `data/`：本地 SQLite、PDF、Markdown 与向量等运行数据，不纳入版本控制。

默认使用 SQLite、进程内任务、本地对象存储和数据库向量检索；ARQ、S3、Qdrant 是可选适配器，开发和测试不应无故增加这些服务依赖。

## 安装与运行

要求 Python 3.11 或 3.12、Node.js 22+、npm；CI 使用 Python 3.11 和 Node.js 24。以下命令在仓库根目录运行：

```text
python scripts/setup.py
python scripts/start.py --reload
```

安装脚本创建 `.venv`、安装后端开发依赖、执行 `npm ci`，并仅在缺少 `.env` 时从 `.env.example` 创建。启动脚本加载根目录 `.env`，先执行 Alembic 迁移，再启动 API（8000）与 Web（3000）。支持 `--api-only --reload`、`--web-only` 和 `--production`；后者先构建前端，不自动切换后端安全环境。

生成与嵌入分别使用 `LLM_*`、`EMBEDDING_*` 的 `BASE_URL`、`API_KEY`、`MODEL` 三元组。每组三项需同时配置；整组留空时使用相应本地实现。配置说明见 `.env.example` 和 `docs/development.md`，不要将真实凭据写入示例。

## 检查与测试

安装依赖后，可从根目录执行 `make lint`、`make test`、`make build`。Windows 没有 Make 时，后端在 `apps/api` 目录执行：

```powershell
..\..\.venv\Scripts\python.exe -m ruff check scholarmind tests alembic ../../scripts
..\..\.venv\Scripts\python.exe -m ruff format --check scholarmind tests alembic ../../scripts
..\..\.venv\Scripts\python.exe -m mypy scholarmind
..\..\.venv\Scripts\python.exe -m pytest
```

Linux/macOS 将 `..\..\.venv\Scripts\python.exe` 替换为 `../../.venv/bin/python`。前端检查从根目录执行：

```text
npm --prefix apps/web run lint
npm --prefix apps/web run typecheck
npm --prefix apps/web test
npm --prefix apps/web run build
```

- 后端使用 Pytest、pytest-asyncio 和 pytest-cov，全量覆盖率门槛为 70%；前端使用 Vitest、jsdom 和 Testing Library。检查配置以 `apps/api/pyproject.toml`、`apps/web/package.json` 和 `.github/workflows/ci.yml` 为准。
- 调试时可运行目标测试：在 `apps/api` 使用上述 Python 执行 `-m pytest tests/test_retrieval_chat.py --no-cov`；前端从根目录执行 `npm --prefix apps/web test -- src/lib/sse.test.ts`。局部测试不代表已通过全量覆盖率检查。
- 修改业务行为或修复缺陷时，针对可观察结果和回归风险补充测试。后端沿用 `tests/conftest.py` 的临时数据库、应用和客户端 fixture；外部 HTTP 使用 stub/mock，避免依赖真实 arXiv、付费模型或本地用户数据。
- 按改动范围完成相关静态检查、测试和构建；纯文档修改检查内容与差异即可。交付说明实际执行的检查及结果，未执行的检查不要声称通过。

## 代码与变更约定

- 遵循 `.editorconfig`：UTF-8、LF、末尾换行；Python 四空格，其余所列代码与配置文件两空格，Makefile 使用制表符。Python 行长 100，遵循 Ruff 和严格 Mypy 配置。
- 保持现有分层：路由处理 HTTP、依赖和协议转换，业务逻辑放入 service，复用 repository 与领域校验。延续异步数据库和 HTTP 调用方式。
- 前端使用现有 `@/` 路径别名、组件和样式约定；新增界面文案接入已有语言上下文，并兼顾中英文。避免在组件中重复实现 API 请求或 SSE 解析。
- 修改 API 字段、错误或 SSE 事件时，同步核对 `api/schemas.py`、前端 `types/api.ts`、客户端、消费组件及相关测试；不要只更新一端。
- 数据模型变更应新增 Alembic 迁移，不重写已应用的迁移。检查生成内容、约束与降级逻辑，验证全新数据库和已有数据库的升级路径。Windows 在根目录使用 `.venv\Scripts\python.exe -m alembic -c apps/api/alembic.ini upgrade head`。
- 依赖版本由 `apps/api/pyproject.toml` 和 `apps/web/package.json` 管理；前端依赖变更同步更新 `package-lock.json`，确保 `npm ci` 可复现。只为当前任务引入必要依赖。
- 配置、启动方式或对外行为发生变化时，更新 `.env.example`、`README.md` 或对应 `docs/` 文档。提交说明应描述具体变更和验证结果，不混入无关格式化。

## 必须保持的业务与安全约束

- 论文、PDF、会话与领域检索记录遵守 owner 授权；单篇全文检索始终限定 `paper_id`，会话同时校验 owner、论文和会话 ID。可选 Qdrant 查询保留 `paper_id AND namespace` 过滤及返回数据复核。
- 摄取保持 `QUEUED → DOWNLOADING → PARSING → INDEXING → READY/FAILED` 状态机；PDF、Markdown、分块和向量全部成功后才能进入 `READY`。保留提交、任务交接与重试的幂等性，不伪造成功状态。
- arXiv 下载和领域检索使用固定目标或精确允许列表；保留逐跳重定向验证、字节与页数限制、对象路径校验。浏览器不能控制服务端请求目标。
- 浏览器经 `/api/backend` 同源 BFF 访问后端 `/api/v1` 业务路由；内部地址与 Token 由服务端配置。模型 Key 和 API Token 不进入客户端代码、`NEXT_PUBLIC_*`、日志、URL 或 SSE。
- 单篇问答保持页码、章节及 `S1..Sn` 引用可追溯，SSE 使用 `meta`、`token`、`done`，流开始后的失败使用 `error`。模型失败不能持久化空答案或伪造完成状态。
- 领域报告只综合 arXiv 元数据和摘要，验证结构与 `P1..Pn` 引用；用户选择精读后才进入单篇 PDF 摄取。论文文本和摘要属于不可信来源，不能覆盖系统指令。
- 嵌入不可用或模型不匹配时，只能在当前论文内安全降级；保留向量数量、顺序、有限数值和维度校验。
- 不提交 `.env`、凭据、`data/`、数据库或构建缓存，也不要以修复开发环境为由清空用户数据。详细约束见 `docs/architecture.md` 和 `docs/security.md`。
