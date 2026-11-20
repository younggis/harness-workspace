# Harness Workspace 技术文档

版本：v1.0（2026-11-20） · 代码结构 / API / 配置 / 数据 / 测试参考

## 1. 技术栈

| 层 | 选型 | 版本/说明 |
|---|---|---|
| 前端 | Vue 3 + Element Plus + Vite + TypeScript | `apps/portal/` |
| API | FastAPI + Pydantic v2 + SQLAlchemy 2 + Alembic | Python 3.11 |
| Worker | Python + docker-py | 租约队列 / 对账 |
| 网关转发 | FastAPI + websockets | relay，HMAC 签名 |
| 模型代理 | FastAPI + httpx | OpenAI 兼容，DeepSeek |
| 边缘 | nginx 1.27-alpine | HTTP→HTTPS / SPA / 分流 |
| 数据库 | PostgreSQL（宿主 127.0.0.1:5432/postgis） | 仅 `harness`/`harness_test` schema |
| 运行镜像 | 锁定 dsh `0.2.2-rc.4` | `upstream.lock.json` |
| 测试 | pytest + TestClient (SQLite) | 离线 / 集成 / E2E / live |

## 2. 仓库结构

```
apps/portal/       前端（登录/工作台/管理/文件/终端）
services/api/      控制面 API、网关、票据、审计、SCIM/令牌
services/worker/   DockerRuntimeDriver、租约队列、对账
services/relay/    签名转发
services/llm/      模型代理、预算、流式
runtime/base/      dsh 镜像入口、适配器、文件服务、PTY
common/            模型/配置/安全/DB/错误包络
db/                角色引导 bootstrap.psql
migrations/        Alembic 0001–0006
infra/nginx/       开发/生产 nginx 配置与证书
compose*.yaml      开发/生产拓扑
scripts/           PowerShell/Python 统一入口、探针、演练
contracts/ tests/  上游契约与各层测试
docs/              本文档集与验收记录
```

## 3. API 参考

统一错误包络：`{"error":{"code","message","request_id","retryable"}}`。
写操作（除 `/internal`、`/health`、`/scim/`）需 `Origin` 与 `X-CSRF-Token`；空间动作需 `Idempotency-Key`。

### 身份
| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/auth/login` | 登录（Argon2id/失败限流/MFA） |
| GET | `/api/me` | 当前用户、租户(含 role)、csrf |
| POST | `/api/auth/logout` | 登出并撤销派生会话 |
| POST | `/api/auth/active-tenant` | 切换租户（校验 membership） |
| GET | `/api/auth/oidc/config` `/start` `/callback` | OIDC |
| POST | `/api/auth/mfa/enroll` `/verify` `/disable` `/complete` | TOTP |

### 租户/用户/空间（管理）
| 方法 | 路径 | 说明 |
|---|---|---|
| POST/GET | `/api/admin/tenants` | 租户 CRUD |
| PATCH | `/api/admin/tenants/{tid}` | 改租户配置/状态 |
| POST/GET | `/api/admin/users` | 用户 CRUD |
| PATCH | `/api/admin/users/{uid}` | 改用户 |
| POST | `/api/admin/users/{uid}/password` | 重置密码 |
| PUT | `/api/admin/tenants/{tid}/members/{uid}` | 设置成员角色/状态 |
| GET | `/api/admin/tenants/{tid}/members` `/workspaces` | 成员/空间列表 |
| GET | `/api/admin/users/{uid}/sessions` | 会话列举 |
| DELETE | `/api/admin/sessions/{sid}` | 吊销会话 |
| GET | `/api/admin/audit` `/api/admin/tenants/{tid}/audit` | 审计 |
| GET | `/api/admin/tenants/{tid}/usage` | 用量 |
| GET/POST | `/api/templates` `/api/admin/templates` | 模板 |

### 空间（用户）
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/workspaces` `/api/workspaces/{wid}` | 空间列表/详情 |
| POST | `/api/workspaces/{wid}/actions/{action}` | start/stop/rebuild/disable/enable |
| GET | `/api/operations/{oid}` | 操作状态 |
| POST | `/api/workspaces/{wid}/entry-tickets` | 创建一次性票据 |
| POST | `/_platform/enter` | 票据兑换（Host/Origin 绑定） |
| GET | `/_platform/me` | 空间内身份 |

### 文件与实时
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/_platform/files` | 列目录 |
| GET/PUT/DELETE | `/_platform/file` | 读/写/删（If-Match / If-None-Match） |
| POST | `/_platform/directories` `/_platform/moves` | 建目录/移动 |
| WS | `/_platform/terminal` `/{path}` | 终端/原生 dsh WS |

### 身份供应与服务账号
| 方法 | 路径 | 说明 |
|---|---|---|
| GET/POST | `/scim/v2/Users` | SCIM 列表/创建 |
| GET/PATCH/DELETE | `/scim/v2/Users/{uid}` | SCIM 详情/改/停用 |
| POST/GET | `/api/me/tokens` | 创建/列举 API token |
| DELETE | `/api/me/tokens/{tid}` | 撤销 token |

## 4. 配置参考（`.env.local`，绝不提交）

| 变量 | 用途 |
|---|---|
| `APP_ENV` `INSTALLATION_ID` `COMPOSE_PROJECT_NAME` | 环境/安装标识/项目隔离 |
| `PORTAL_ORIGIN` `WORKSPACE_HOST_SUFFIX` | 浏览器 Origin / 空间域名 |
| `PG_HOST/PORT/DATABASE/SCHEMA` | 宿主 PG 与专用 schema |
| `PG_APP_USER/PASSWORD` `PG_MIGRATION_USER/PASSWORD` | 应用/迁移角色（生产走 `_FILE`） |
| `PG_LLM_USER/PASSWORD` | 用量写入角色 |
| `PG_TEST_*` | 测试 schema/角色 |
| `DEEPSEEK_BASE_URL/MODEL/API_KEY` `REASONING_EFFORT` `THINKING_ENABLED` | 模型代理 |
| `RELAY_SIGNING_KEY` `SESSION_SIGNING_KEY` `HARNESS_WORKSPACE_TOKEN_SEED` | 签名/凭据派生 |
| `OIDC_*` `MFA_REQUIRED` `SCIM_BEARER_TOKEN` | 企业身份 |
| `DSH_VERSION` `DSH_NPM_PACKAGE` | 上游锁定 |
| `EDGE_PORT` | 边缘端口 |

生产环境敏感项通过 Docker secrets 注入：`<NAME>_FILE → /run/secrets/<name>`（`init-secrets.ps1` 生成）。

## 5. 数据与迁移

- Alembic：`0001_init` → `0002_lifecycle_constraints` → `0003_template_dsh_version` → `0004_credential_hash_reissue` → `0005_user_mfa` → `0006_api_tokens` → `0007_tenant_resources`。
- 当前 schema 版本：`0007_tenant_resources`（harness 与 harness_test 均已升级）。
- 租户资源策略：`common/harness_common/limits.py`（平台上限）、`services/api/app/resources.py`（校验/继承/总量检查）、`docs/TENANT_RESOURCES.md`（方案）。
- 引导：`db/bootstrap.psql` 创建专用角色；迁移角色拥有 DDL，应用角色仅 DML。

## 6. 网关代理链路（排障关键）

```
浏览器 (空间 Cookie)
  → edge nginx: location /_platform/ /api/ → api:8000
  → gateway._proxy: 校验空间会话/Host/epoch → relay 签名
  → relay:8081 → 空间适配器 (127.0.0.1:3080)
  → dsh
```

- 适配器 `_safe_headers` 清除平台 Cookie/Authorization，只注入 dsh 会话 Cookie。
- `extra_hosts` 把 `w-<uuid>...` 钉到 127.0.0.1，解决隔离网无 DNS 问题。
- WS 同理，relay 用 HMAC 绑定 (method,path,workspace,generation)。

## 7. 测试体系

| 套件 | 命令 | 说明 |
|---|---|---|
| offline | `pytest tests/ -q` | SQLite，无需密钥/Docker |
| integration | `HARNESS_INTEGRATION=1 pytest` | 真实 PG/Docker |
| e2e | `HARNESS_E2E=1` | 真实浏览器 |
| live | 有效 DeepSeek key | 产生费用 |

当前结果：离线 **94 passed / 11 skipped**；带集成环境 **99 passed / 6 skipped**；前端 **9 passed**（路由守卫 + newId + 登录态缓存）。
性能：`apps/portal/vite.config.ts` 路由级拆包 + manualChunks；`services/llm/llm/main.py` 进程级 httpx 连接池 + `MODEL_MAX_CONCURRENT` 信号量；保留策略见 `scripts/prune-history.ps1`，Docker 地址池示例见 `infra/docker/daemon.json`。
关键模块：`common/harness_common/quotas.py`（API/worker 共用启动配额）、`services/api/app/ratelimit.py`（Redis 登录限流）、`services/worker/worker/driver.py:gc_networks`（孤儿网络 GC）、`services/api/app/ratelimit.py`、`services/api/app/permissions.py` + `deps.py`（API token scope 强制）、`common/harness_common/password_policy.py`。
专项探针：`scripts/runtime_isolation_probe.py`（容器内隔离）、`scripts/fileservice_probe.py`（容器内文件服务，19/19 通过）。

## 8. 上游锁定与升级门禁

- `upstream.lock.json` 锁定 dsh 版本与 npm 包；`contracts/upstream/` 保存契约样本。
- 升级：`scripts/upgrade-check.ps1 -Version <新版本>` → 构建候选镜像 → 校验版本 → 契约/离线测试 → 通过才注册新模板；详见 `docs/upgrades.md`。
