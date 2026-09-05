# 运维与故障排查

## 探针与指标

| 路由 | 语义 | 失败动作 |
|---|---|---|
| `/health/live` | API 事件循环仍可响应 | 重启 API 进程 |
| `/health/ready` | SQLite、本地对象目录和检索器可用 | 查看返回的 `checks` 与应用日志 |
| `/metrics` | Prometheus exposition | 只向本机或可信监控网络开放 |

默认 inline 模式的 HTTP、摄取、问答和 fallback 指标都在 API `:8000/metrics`。只有显式启用 ARQ 独立 Worker 时，Worker 才在 `WORKER_METRICS_PORT` 暴露自己的进程内指标。

主要指标：

- `scholarmind_http_requests_total{method,route,status}`
- `scholarmind_http_request_duration_seconds`
- `scholarmind_ingestion_jobs_total{result,error_code}`
- `scholarmind_ingestion_duration_seconds`
- `scholarmind_ingestion_stage_transitions_total{stage}`
- `scholarmind_chat_generations_total{result}`
- `scholarmind_chat_generation_duration_seconds`
- `scholarmind_retrieval_fallback_total{reason}`
- `scholarmind_retention_deletions_total{result}`

建议关注 API 5xx、摄取失败、长期无 complete、chat failed、retrieval fallback 持续增长和 `data/` 磁盘占用。

## 日志与请求关联

`ENVIRONMENT=production` 时输出单行 JSON。API 接受合法 `X-Request-ID`，否则生成 UUID；提交任务时传播到摄取链路。关键字段：

- `request_id`、`method`、`route`、`status_code`、`duration_ms`；
- `job_id`、`paper_id`、`attempt`、`stage`；
- `error_code`、`error_type`。

日志不应记录 API Key、Bearer Token、完整 query 或论文正文。排查客户端错误时先用响应 `error.request_id` 搜 API 日志，再按 `job_id` 查看摄取阶段。

## 常见故障

| 现象/错误 | 原因 | 处理 |
|---|---|---|
| Paper 长期 `queued` | inline task 所在 API 曾被强制终止 | 再次提交相同 arXiv ID；若仍 queued，调用 `/retry` 修复队列交接 |
| `unsafe_redirect` | arXiv 跳转到非 allow-list 域名 | 不要临时开放任意域名；核实官方变更后更新 allow-list |
| `pdf_too_large` | PDF 超过配置 | 评估内存/磁盘后再提高 `MAX_PDF_BYTES` |
| `no_extractable_text` | 扫描件或无可提取文字 | 当前无 OCR；保持 FAILED，不要伪造 READY |
| `embedding_authentication_failed` | Embedding Key 无效 | 检查 `EMBEDDING_API_KEY`，Key 不会出现在请求 URL |
| `embedding_request_rejected` | model、base URL 或协议不兼容 | 确认 Base URL 以 API 根 `/v1` 结尾，模型支持 `/embeddings` |
| `invalid_embedding_response` | 数量、index、维度或数值非法 | 查看兼容服务响应格式；必须返回 OpenAI `data[].embedding` |
| 问答持续词法 fallback | 查询 embedding 失败或已更换模型 | 检查 `scholarmind_retrieval_fallback_total`；恢复服务后重建旧论文向量 |
| Chat SSE 无 token | 兼容服务未按 OpenAI SSE 返回 delta | 确认支持 `stream=true`、`choices[0].delta.content` 和 `[DONE]` |
| Chat SSE 中断 | 上游超时或反向代理缓冲 | 增大读取超时并关闭 SSE buffering |
| PDF iframe 空白 | 对象丢失、Content-Type 或 BFF 错误 | 检查 `data/objects`、API/BFF request ID 和浏览器控制台 |
| 429 | 本地限流或模型服务限流 | 等待 `Retry-After`；检查模型配额与并发 |
| 503 readiness | SQLite/目录不可访问 | 查看 `checks`，检查权限、磁盘空间和数据库文件 |

## arXiv 检索超时与 502/503

先区分模型接口和 arXiv：单篇问答可用，但 `/research/search` 返回 `arxiv_temporarily_unavailable`，表示失败发生在 arXiv 请求阶段。查看响应的 `request_id`，对应日志 `arxiv_search_attempt_failed` 会记录尝试次数、异常类型和上游 HTTP 状态，不记录查询内容或凭据。

项目已对连接错误、读取超时、协议中断和 HTTP 408/429/5xx 自动重试，默认配置为：

```dotenv
ARXIV_SEARCH_MIN_INTERVAL_SECONDS=3
ARXIV_SEARCH_MAX_ATTEMPTS=3
ARXIV_SEARCH_ATTEMPT_TIMEOUT_SECONDS=20
ARXIV_SEARCH_TOTAL_TIMEOUT_SECONDS=65
```

`MAX_ATTEMPTS` 包含第一次请求。每次请求最多 20 秒，重试通常等待 3 秒、6 秒；服务器提供更长的 `Retry-After` 时遵守该等待时间，支持秒数和 HTTP 日期。排队、重试和下载合计最多 65 秒；若等待时间超过剩余预算，则返回暂不可用，而不会提前重试。查询客户端保持串行连接，失败请求也受间隔限制。包含中文检索词准备在内的业务请求最多 110 秒，以便在 BFF 的 130 秒截止时间前返回明确错误。参数错误、重定向和非法响应不会反复重试。

[arXiv 官方规则](https://info.arxiv.org/help/api/tou.html)要求 legacy API 同时最多一个连接、请求至少间隔 3 秒；多进程或多机器部署还需统一控制总请求速率。[官方状态页](https://status.arxiv.org/)可辅助排查，但显示正常并不能保证每次查询成功。

在启动服务的同一个 PowerShell 终端，用不需要 Key 的官方示例检验当前网络：

```powershell
.\.venv\Scripts\python.exe -c 'import httpx; r = httpx.get("https://export.arxiv.org/api/query", params={"search_query": "all:electron", "start": 0, "max_results": 1}, timeout=20); print(r.status_code, r.headers.get("content-type")); r.raise_for_status()'
```

- 示例成功、业务查询间歇失败：保留自动重试，先检索 5–10 篇，适当限定分类/日期；可在历史领域图谱中查看已保存结果。缓存仍按 owner 和完整查询条件隔离。
- 示例也无法连接：检查当前终端的代理是否可用。后端 HTTPX 继承 `HTTPS_PROXY`、`HTTP_PROXY` 和 `NO_PROXY`；浏览器能访问网页不代表 Python 进程使用了同一路径。
- 使用现有本地 HTTP 代理时，在同一终端设置代理环境变量后重新启动服务。以下 `7890` 是当前验收环境已使用的端口，应按实际代理端口调整：

```powershell
$env:HTTPS_PROXY = 'http://127.0.0.1:7890'
$env:HTTP_PROXY = 'http://127.0.0.1:7890'
$env:NO_PROXY = '127.0.0.1,localhost,::1'
python scripts/start.py --production
```

这些变量只影响该终端及其启动的子进程。无需调整 LLM Key、清空数据库或改变 arXiv 允许列表。更改 `.env` 中的重试参数后也需要重启 API。持续故障时查看最后一次上游状态；重试只能缓解短暂故障，不能修复代理连接中断或 arXiv 服务持续不可用。

## OpenAI 兼容接口诊断

生成请求目标必须是：

```text
{LLM_BASE_URL}/chat/completions
```

Embedding 请求目标必须是：

```text
{EMBEDDING_BASE_URL}/embeddings
```

例如 `BASE_URL=https://api.openai.com/v1`。不要把完整 endpoint 再填入 Base URL，否则会得到重复路径。模型服务使用自签名证书时应正确安装本机 CA，而不是关闭 TLS 验证。

服务返回 401/403 时检查 Key；404 通常表示 Base URL 路径错误；400 通常表示模型名或兼容字段不支持；429/5xx 在摄取阶段会按配置重试。

## 重试语义

- 可重试：网络超时、上游 429/5xx、可选对象/向量服务暂时不可用；
- 不可重试：非法、过大、加密 PDF，无文本，模型鉴权失败或无效协议响应；
- 达到 `INGESTION_MAX_ATTEMPTS` 后进入 `FAILED`；
- FAILED 调用 `/retry` 会创建新 job；数据库已提交但 inline handoff 失败的 QUEUED job 会复用确定 job ID 补投；
- 只有 embedding 已写入并完成索引事务，论文才进入 `READY`。

## 数据保留与清理

默认数据都在根目录 `data/`。可先停止应用并删除整个目录来清空工作区。不要只删除 SQLite 而保留对象，或只删除对象而保留 READY 记录。

`PAPER_RETENTION_DAYS` 的定时清理由可选 ARQ Worker cron 执行；默认 inline 模式不会自行启动独立 cron。单机部署应由操作系统计划任务定期执行维护流程，或在明确备份后人工清理。

## 恢复顺序

1. 停止 API 与 Web；
2. 恢复同一备份时点的 `data/scholarmind.db` 和 `data/objects/`；
3. 恢复受保护的 `.env`；
4. 执行 `alembic upgrade head`；
5. 启动 API/Web 并检查 `/health/ready`；
6. 提交一篇测试论文，验证 embedding 已写入、问答有页码引用；
7. 对处于 QUEUED/FAILED 的历史 job 按需重新提交或 retry。
