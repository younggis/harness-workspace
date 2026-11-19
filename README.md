# harness-workspace

基于 DeepSeek Harness 的多租户 AI 工作台。管理员可分配和管理隔离的 Docker 工作空间，用户可在浏览器中查看 Agent 执行过程、编辑文件并使用 Linux 终端。

实现规格见 `Harness-Implementation-Guide.md`；真实执行结果与「待验证」清单见
`docs/verification.md`；上游版本锁定见 `upstream.lock.json`。

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
连接注册表与撤权、生命周期约束、契约样本与升级门禁已落地（见 `docs/verification.md` 1.12–1.14）；
仍待推进：剩余 P0 隔离/停用 E2E、备份恢复演练、容量基线、远程/HTTPS 部署、K8s RuntimeDriver。

## 当前验收状态（摘要）

- ✅ 真实 PG 引导、迁移（14 张表，0001_init）、管理员创建、容器→宿主认证登录
- ✅ 离线 22 项通过（身份/租户/隔离/票据/幂等/配额/对账/签名）
- ✅ 镜像构建、浏览器登录、租户/空间分配、票据兑换、文件与终端、真实 DeepSeek 对话
- ✅ T14 完整业务链：Agent 用 Python 标准库统计三点 GeoJSON 写出 `result.json`
  （`{"count": 3, "bbox": [0, 0, 3, 4]}`），网页与终端均可读取
- ✅ Test Tenant / 登录 / 会话 / 工作空间进入实测通过（`docs/verification.md` 1.9 / 1.10）
- ⚠️ A2/B1 跨租户越权实测、停用后终端关闭、备份恢复演练、容量基线 T17 待验证
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
