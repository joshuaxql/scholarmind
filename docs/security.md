# 安全模型

## 信任边界

1. 浏览器输入不可信；
2. arXiv 响应、PDF 内容和重定向不可信；
3. PDF 文本对模型是不可信数据，不能成为系统指令；
4. Next.js BFF 是持有内部 API Token 的可信服务端；
5. SQLite、对象目录和 `.env` 只应由运行 ScholarMind 的本机账号访问；
6. OpenAI 兼容服务是管理员配置的上游，不接受浏览器提供的目标地址。

## 已实现控制

### SSRF 与下载

- 只接受规范化 arXiv ID，URL host 必须精确属于 allow-list；
- 拒绝 credentials、异常端口、query/fragment 和非 HTTP(S) scheme；
- 后端自行构造 canonical HTTPS URL；
- 关闭自动重定向，每一跳重新验证 scheme、host 和 port；
- 同时检查 `Content-Length` 与实际流字节数；
- 验证 `%PDF-` magic、最大页数、加密和无文本 PDF；
- XML 使用 `defusedxml`。

### 身份与授权

- `ENVIRONMENT=production` 强制 `AUTH_REQUIRED=true`，Token 至少 32 字符；
- 使用常量时间 Token 比较；
- Token hash 派生 owner，不持久化原 Token；
- 所有论文、PDF 和会话查询均绑定 owner；
- BFF 只向固定 `API_INTERNAL_URL` 加凭据，不接受调用者提供目标 URL；
- BFF 限制方法、路径和请求体大小。

### 本地数据与检索隔离

- SQLite 查询按 owner/paper 过滤；
- database retrieval 的 chunk SQL 强制 `paper_id`；
- 可选 Qdrant 查询使用 `paper_id AND namespace` 并复查 payload；
- 对象键拒绝绝对路径、`..` 和反斜线；
- `.env`、`data/` 和日志应由独立低权限本机账号拥有，禁止其他本机用户读取；
- 备份中的 SQLite、PDF 和 Key 应加密并限制访问。

### OpenAI 兼容服务

- `LLM_API_KEY` 和 `EMBEDDING_API_KEY` 只放在 `Authorization: Bearer` 请求头，不放 URL、日志或 SSE；
- Base URL 必须是绝对 HTTP(S) URL，并拒绝内嵌 credentials、query 和 fragment；
- Base URL 只能由可信管理员通过环境配置，业务请求不能覆盖；
- 两套 Key 独立，建议按最小权限和最小配额签发；
- 响应会验证 JSON/SSE 结构、向量数量、index、有限数值和维度；
- HTTP 错误不会把上游响应正文直接返回浏览器。

如果兼容服务运行在本机，优先绑定回环地址。远程服务必须使用有效 TLS；不要通过关闭证书验证解决自签名证书问题，应安装可信 CA。

### 提示注入

System prompt 明确把论文来源视为不可信数据，只允许依据 `S1..Sn` 来源回答。论文内容放在显式 `<paper_sources>` 块中；前端 Markdown 不启用原始 HTML。

这只能降低而不能彻底消除间接提示注入。医学、法律、财务或科研结论等高风险用途必须人工复核原 PDF 引用。

## 当前限制

- 共享 Bearer Token 适合个人或私有单团队工作区，不是终端用户认证；
- 没有 OIDC、MFA、组织 RBAC、审计导出或每用户撤销；
- API Token 经 BFF 代表全部浏览器访问者，因此 Web 必须位于受控主机/网络或前置身份代理；
- 默认开发模式关闭鉴权且绑定 `127.0.0.1`，不得改为所有网卡后继续无鉴权运行；
- inline 内存限流适合单 API 进程，重启会清空计数；
- PDF 在浏览器内置 viewer 中渲染，仍应视为不可信文件；
- 应用不知道边缘 TLS 状态，因此 HSTS 由 HTTPS 代理添加。

## 上线检查清单

- [ ] API 继续绑定回环地址，只向外提供受 TLS 保护的 Web
- [ ] Web 前有身份代理或等价访问控制
- [ ] `ENVIRONMENT=production`、`AUTH_REQUIRED=true`
- [ ] API、LLM 和 embedding Key 随机、独立且不进入 Git/日志
- [ ] `.env` 与 `data/` 仅运行账号可读
- [ ] `CORS_ORIGINS` 只有实际 HTTPS origin
- [ ] OpenAI 兼容 Base URL 由管理员固定且使用可信 TLS
- [ ] `/metrics` 只允许可信监控访问
- [ ] 备份加密，恢复、Token 轮换和事件响应经过演练
- [ ] Python/npm 依赖持续审计并及时升级

## Token 轮换

本地 `/settings` 页面可更新根目录 `.env`，但不会回显已有 Token、模型 Key、S3 密钥或带凭据的连接字符串。前端仅提交被修改的字段；设置响应使用 `Cache-Control: no-store`，错误中不包含配置输入值。设置路由同时要求回环连接、回环监听地址、自定义请求标记和既有鉴权；BFF 另检查浏览器 Host/Origin，拒绝跨站请求及公网监听下的配置编辑。反向代理应禁止对外代理设置路由。

配置写入不热更新运行中的 Token，必须重启前后端后生效。启用鉴权时，内部代理 Token 必须与 API Token 一致，或留空让统一启动器自动沿用 API Token。

共享 API Token 只能单值校验，更新后旧 Token 立即失效：

1. 在维护窗口停止 Web/API；
2. 同时更新 `API_BEARER_TOKEN` 与 `API_INTERNAL_BEARER_TOKEN`；
3. 重启并验证 `/health/ready` 与 BFF 请求；
4. 检查 401/5xx 并安全销毁旧 secret。

模型 Key 可以分别轮换：更新对应 `.env` 值后重启 API。若需要无中断双 Token 轮换，应先扩展鉴权模块支持 active/next token。
