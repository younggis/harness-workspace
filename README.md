# harness-workspace

基于 DeepSeek Harness 的多租户 AI 工作台。管理员可分配和管理隔离的 Docker 工作空间，用户可在浏览器中查看 Agent 执行过程、编辑文件并使用 Linux 终端。

实现规格见 `Harness-Implementation-Guide.md`；真实执行结果与「待验证」清单见
`docs/verification.md`；上游版本锁定见 `upstream.lock.json`。

## 文档集
- 需求：`docs/REQUIREMENTS.md`（功能/非功能需求、T01–T17 验收映射）
- 设计：`docs/DESIGN.md`（架构、对象模型、时序、隔离/安全设计、威胁模型）
- 技术：`docs/TECHNICAL.md`（技术栈、API、配置、数据、测试、代理链路）
- 部署：`docs/DEPLOYMENT.md`（开发/生产、secrets、TLS、网络、升级回滚）
- 操作：`docs/OPERATIONS.md`（日常流程、Runbook、巡检、故障排查、应急响应）
- 验收：`docs/verification.md`（真实执行记录与极端条件测试 1.28/1.29）

## 环境
Windows 11 · Docker Desktop（Linux 容器）· FastAPI · Vue 3 · 本机 PostgreSQL(postgis) · DeepSeek。
只操作 PostgreSQL 的 `harness` / `harness_test` 专用 schema；不触碰既有 GIS 表、public、
其他 Docker 项目；数据库口令与模型密钥仅从 `.env.local`（gitignore）读取。

## 启动（PowerShell）

```powershell
Copy-Item .env.example .env.local
.\scripts\init-local.ps1
# 维护者交互输入 postgres 口令，仅一次：
psql -h 127.0.0.1 -p 5432 -U postgres -d postgis -W -f .\db\bootstrap.psql
.\scripts\doctor.ps1
.\scripts\build.ps1
.\scripts\migrate.ps1
.\scripts\admin-create.ps1
.\scripts\up.ps1
```

- **浏览器访问**：`http://portal.127.0.0.1.nip.io:8080`
  （本机 `portal.localhost` 在 WinINET 下解析失败，改用回环 DNS，未改 hosts；
  代理需把这些 Host 加入「不使用代理」列表，见 `docs/verification.md` 2.3）
- **空间域名**：`http://w-<uuid>.127.0.0.1.nip.io:8080`
- **首个管理员**：由 `.\scripts\admin-create.ps1` 交互式创建，无内置默认密码。

## 测试

```powershell
.\scripts\test.ps1 -Suite offline       # 22 passed，无需密钥/Docker
.\scripts\test.ps1 -Suite integration   # 真实 Docker + PG（需 HARNESS_INTEGRATION=1）
.\scripts\test.ps1 -Suite e2e           # 真实浏览器（需 HARNESS_E2E=1）
.\scripts\test.ps1 -Suite live          # 真实 DeepSeek（需有效密钥，产生费用）

# 上游 dsh 升级门禁（构建候选镜像 + 契约/离线测试 + 记录）
.\scripts\upgrade-check.ps1 -Version 0.2.2-rc.4
```

## 生产形态（HTTPS + Secrets）
```powershell
.\scripts\init-secrets.ps1
.\scripts\gen-devcert.ps1            # 仅自签名开发证书；生产请替换为真实证书
docker compose --env-file .env.local -p harness-prod -f compose.prod.yaml up -d
```
`compose.prod.yaml` 使用 Docker secrets（`<NAME>_FILE` 注入）、HTTPS/HSTS、资源限制与日志轮转。
端口 8080(HTTP 跳转)/8443(HTTPS)。生产需把证书换成受信任 CA，并把 `PORTAL_ORIGIN` 改为 https 域名。

## 企业身份（OIDC / MFA）
在 `.env.local` 填入 OIDC 配置后，登录页自动显示“使用企业账号登录”：
```
OIDC_ISSUER=https://idp.example.com/realms/harness
OIDC_CLIENT_ID=harness
OIDC_CLIENT_SECRET=...
OIDC_REDIRECT_URI=http://portal.127.0.0.1.nip.io:8080/api/auth/oidc/callback
OIDC_AUTO_PROVISION=false
```
回调 URI 必须在 IdP 注册。支持 Authorization Code + PKCE、JWKS 验签、nonce 校验；
`OIDC_AUTO_PROVISION=true` 时按 email JIT 开通账号。
TOTP MFA：用户登录后调用 `POST /api/auth/mfa/enroll` 获取密钥，用验证器确认
`POST /api/auth/mfa/verify`；启用后密码正确仅返回 `mfa_required`，再提交
`POST /api/auth/mfa/complete` 才建立会话。真实 IdP 联调待现场验证。

## 产品化后续
OIDC/MFA/SCIM/服务账号、细粒度 RBAC、跨进程撤权、隔离渗透、PITR、HTTPS+secrets、
升级门禁均已落地（见 `docs/verification.md` 1.12–1.29）；K8s RuntimeDriver 为预留扩展点。

## 当前验收状态（摘要）

- ✅ 真实 PG 引导、迁移（14 张表，`0006_api_tokens`）、管理员创建、容器→宿主认证登录
- ✅ 全量测试：离线 **51 passed / 7 skipped**，带集成环境 **82 passed / 6 skipped**
- ✅ 全流程浏览器 E2E：登录/管理/租户切换/空间进入/真实 DeepSeek 对话/文件/终端/RBAC/登出
- ✅ 极端条件：26 项离线异常测试 + 19/19 容器内文件服务探针 + 真实网关票据/Origin/Host/跨空间网络隔离
- ✅ 备份恢复 / PITR / 容量基线 / 三空间隔离探针全通过
- ⚠️ 待验证（需环境/授权）：真实 IdP、受信任证书 HTTPS、现有 Windows PG 主从/归档、
  第三方渗透测试与合规材料、T17 完整压测（冷/热启动 ×5、1/2/4 空间并发）
  详见 `docs/verification.md` 第 4 节 T01–T17。

## 结构

```
apps/portal/       Vue 3 门户/管理/文件/终端
services/api/      FastAPI 控制面、网关、票据、审计
services/worker/   DockerRuntimeDriver、租约队列、对账
services/relay/    签名转发（HTTP/WS）
services/llm/      OpenAI 兼容模型代理、预算、流式
runtime/base/      dsh 锁定镜像、文件服务、PTY、适配器
db/ migrations/    专用角色引导与 schema 内迁移
infra/ compose.yaml 边缘与服务拓扑
scripts/           PowerShell 统一入口、备份/恢复、冒烟
contracts/ tests/  上游契约、离线/集成/E2E/live
```
