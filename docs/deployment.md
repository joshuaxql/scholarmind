# 本机部署与升级

## 推荐模式

ScholarMind 默认作为一台可信主机上的单实例应用运行：

```text
Browser → Next.js Web/BFF :3000 → FastAPI :8000
                                      ├→ SQLite ./data/scholarmind.db
                                      ├→ local files ./data/objects
                                      ├→ arXiv
                                      └→ OpenAI-compatible APIs
```

API 默认绑定 `127.0.0.1`。仅在确实需要局域网访问并已配置防火墙、鉴权和 TLS 时才修改 `API_HOST`。浏览器不应直接持有 `API_BEARER_TOKEN`，也不要创建 `NEXT_PUBLIC_API_*` 变量。

## 首次安装

```bash
python scripts/setup.py
```

然后编辑根目录 `.env`。本机仅自己使用时可以保持：

```dotenv
ENVIRONMENT=development
API_HOST=127.0.0.1
AUTH_REQUIRED=false
DATABASE_URL=sqlite+aiosqlite:///./data/scholarmind.db
QUEUE_MODE=inline
STORAGE_BACKEND=local
RETRIEVAL_BACKEND=database
```

模型配置：

```dotenv
LLM_BASE_URL=https://provider.example/v1
LLM_API_KEY=<secret>
LLM_MODEL=<chat-model>

EMBEDDING_BASE_URL=https://embedding-provider.example/v1
EMBEDDING_API_KEY=<secret>
EMBEDDING_MODEL=<embedding-model>
```

若 Web 会被其他用户访问，应额外设置：

```dotenv
ENVIRONMENT=production
AUTH_REQUIRED=true
API_BEARER_TOKEN=<at-least-32-random-characters>
WEB_ORIGIN=https://papers.example.com
CORS_ORIGINS=["https://papers.example.com"]
API_INTERNAL_BEARER_TOKEN=<same-value-as-API_BEARER_TOKEN>
```

生成随机 Token：

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

## 启动方式

开发或可信工作站：

```bash
python scripts/start.py --reload
```

长期运行：

```bash
python scripts/start.py --production
```

启动器会执行数据库迁移、构建前端（production 模式）并管理 API/Web 子进程。长期服务建议再由操作系统服务管理器托管该命令，使其在登录会话结束后继续运行并在异常退出时重启。

也可以分别托管：

```bash
# 升级数据库
.venv/bin/python -m alembic -c apps/api/alembic.ini upgrade head

# API
.venv/bin/python -m uvicorn scholarmind.main:app --app-dir apps/api \
  --host 127.0.0.1 --port 8000 --workers 1

# Web（先执行 npm --prefix apps/web run build）
npm --prefix apps/web run start
```

SQLite + inline queue 模式必须保持单个 API worker。多 worker 会让进程内任务和 SQLite 写竞争失去预期语义。

## TLS 反向代理

需要局域网或公网访问时，仅代理 Web `:3000`：

- 强制 HTTPS；
- Web 前增加 OIDC、访问代理或等价身份控制；
- 为 `/api/backend/.../chat/stream` 关闭响应缓冲；
- 上游读取超时至少 150 秒；
- 请求体上限可设为 256 KiB；
- 透传 `X-Request-ID`；
- HSTS 只由确认全站 HTTPS 的边缘代理添加。

Nginx SSE 关键设置：

```nginx
proxy_http_version 1.1;
proxy_buffering off;
proxy_read_timeout 150s;
```

## 队列模式取舍

默认 `QUEUE_MODE=inline` 最适合直接本机运行：提交后由 API 进程异步摄取，不需要单独服务。数据库中的 job 记录仍保留状态，但进程在任务执行期间被强制终止时，需要重新提交同一论文或调用 retry 修复。

如果未来需要任务跨进程重启恢复，可在本机独立安装 Redis，设置 `QUEUE_MODE=arq` 和 `REDIS_URL`，再运行：

```bash
.venv/bin/python -m arq scholarmind.workers.settings.WorkerSettings
```

这属于可选增强，不是默认启动要求。

## 升级

1. 停止 API 与 Web；
2. 备份 `data/` 和 `.env`；
3. 更新源码；
4. 运行 `python scripts/setup.py` 更新依赖；
5. 运行 Alembic：`.venv/bin/python -m alembic -c apps/api/alembic.ini upgrade head`；
6. 执行测试与前端构建；
7. 重新启动并检查 `/health/ready`。

不要在未备份前执行破坏性迁移。应用代码回滚不会自动撤销数据库结构，必要时应使用已验证的 Alembic downgrade 或从备份恢复。

## 修改嵌入模型

每个 chunk 会保存生成它的 embedding provider/model 标识。配置变化后，旧向量不会与新查询向量混用，而会自动降级到词法检索。要获得完整的新模型向量：

1. 备份需要保留的内容；
2. 删除 `data/` 中的旧本地工作区，或使用后续提供的重建流程；
3. 重启并重新提交论文；
4. 验证引用页码和召回结果。

## 备份与恢复

需要备份：

- `data/scholarmind.db`：论文、任务、分块向量和会话；
- `data/objects/`：PDF 与 Markdown；
- `.env`：模型配置和应用凭据，应加密并与数据备份分开保管。

停止应用后复制整个 `data/` 是最简单且一致的备份方式。在线备份 SQLite 时应使用 SQLite backup API，而不是只复制一个正在写入的数据库文件。恢复时先停止进程、恢复同一时点的数据目录、执行迁移，再启动应用。
