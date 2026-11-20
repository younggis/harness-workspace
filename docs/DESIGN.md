# Harness Workspace 设计文档

版本：v1.0（2026-11-20） · 实现对应 `0cbfd74` 及后续

## 1. 设计原则

1. **控制面与数据面分离**：API/worker/relay/llm/edge 是控制面；空间中运行的 dsh 容器是数据面。控制面永不把凭据下传给数据面。
2. **最小权限与默认隔离**：运行时容器生来只在自己的内部网络，默认 bridge 是被显式禁止的（曾发现的重大漏洞，已修复）。
3. **状态由控制面权威裁决**：空间期望态（desired）与实际观测态（observed）分离，worker 对账驱动收敛。
4. **不可变基础设施 + 稳定标识**：卷/网络/容器按 installation+workspace+generation 打标签；冲突标签拒绝接管。

## 2. 架构总览

```
浏览器
  │  portal.127.0.0.1.nip.io / w-<uuid>.127.0.0.1.nip.io
  ▼
edge (nginx) ──▶ api (控制面: 身份/租户/票据/网关/审计)
                  │            │
                  │            └─▶ relay (签名转发 HTTP/WS)
                  │                    │
                  │                    └─▶ llm (模型代理 → DeepSeek)
                  └─▶ worker (租约队列 + 对账)
                         │
                         └─▶ Docker RuntimeDriver
                               创建: 容器 + 卷 + 内部网络
                                │
                              适配器 → dsh (loopback:3080)
```

- `front`：浏览器可达（edge）。
- `backend`：api/relay/llm/worker 互通。
- `control` (`internal: true`)：控制面内部网，无外网出口。
- 每个空间一张 **独立 internal bridge 网络**，relay/llm 由 worker 按需挂入。

## 3. 组件职责

| 组件 | 技术 | 职责 |
|---|---|---|
| portal | Vue 3 + Element Plus | 登录/工作台/管理/文件/终端 UI |
| api | FastAPI | 身份、RBAC、租户/空间、票据、网关代理、审计、用量、SCIM/令牌 |
| worker | Python | DockerRuntimeDriver、租约队列消费、对账、网关重挂 |
| relay | Python WebSocket | 用 HMAC 签名绑定 (method,path,workspace,generation) 转发 |
| llm | FastAPI | OpenAI 兼容代理、预算桶、流式、模型请求记录 |
| edge | nginx | HTTP→HTTPS、SPA 静态、路径分流 |
| runtime | 锁定 dsh 镜像 + 适配器 | 每空间容器：文件服务、PTY、Agent |

## 4. 核心对象模型（14 张表，schema `harness`）

身份域：`users`、`tenants`、`memberships`、`auth_sessions`、`api_tokens`
资源域：`templates`、`workspaces`、`workspace_operations`、`runtime_credentials`、`entry_tickets`、`workspace_sessions`
运行域：`model_requests`、`budget_buckets`、`audit_events`

关键关系：

- `users` ↔ `tenants` 经 `memberships`（role: tenant_admin/member, status）。
- `workspaces` 归属 (tenant_id, owner_id)，唯一约束 `(tenant_id, owner_id)`。
- `workspace_operations` 每空间同时仅一个 queued/running（部分唯一索引）。
- `auth_sessions.active_tenant_id` 决定当前角色上下文；`auth_epoch` 变化使旧票据/会话失效。

## 5. 关键流程时序

### 5.1 登录与角色上下文
```
POST /api/auth/login → 校验 Argon2id → (MFA?) → AuthSession + Cookie
POST /api/auth/active-tenant → 校验 membership → 写 active_tenant_id → 撤销派生会话/票据
GET  /api/me → user + tenants(含 role) + csrf
```

### 5.2 空间启动
```
POST /api/workspaces/{id}/actions/start (Idempotency-Key)
  → 配额校验 → WorkspaceOperation(queued) → desired_state=running
worker 领取租约 → driver.ensure(卷/网) → driver.start(容器)
  → attach_gateway(relay/llm 入网) → 生成凭据 → observed_state=running
```

### 5.3 进入空间
```
POST entry-tickets → 一次性 ticket (短 TTL)
POST /_platform/enter (Host=工作空间域, Origin=portal, ticket)
  → 校验 Host/Origin/epoch/会话 → 原子消费 → WorkspaceSession Cookie → 303
浏览器经 edge → api 网关 → relay → 空间适配器 → dsh
```

### 5.4 停用/停止
```
POST actions/{stop|disable} → desired_state=stopped, auth_epoch++ (disable)
  → connections.close_workspace(id) → 关闭活跃 WS/终端/SSE
worker → driver.stop → 移除容器/网络，吊销凭据
```

## 6. 隔离设计

| 层 | 机制 |
|---|---|
| 身份 | 平台凭据不出控制面；空间会话仅 Cookie；dsh 只看适配器注入的签名 Cookie |
| 计算 | 独立容器：非 root、只读根、cap_drop ALL、no-new-privileges、pids/内存/CPU 限额 |
| 网络 | 每空间独立 `internal: true` bridge；容器 born only on that net；extra_hosts 把公网 authority 钉到 127.0.0.1 |
| 存储 | 独立 project/home 卷，标签校验，跨代复用但不被异标签接管 |
| DNS | 适配器用单一 UPSTREAM_AUTHORITY，避免 Host/Cookie authority 不一致 |

> 关键修复：runtime 曾误接默认 bridge（可访问宿主/外网/其他容器）。现 `driver._container_config` 仅传内部网名，`docker inspect` 可验证 ExtraHosts 与网络归属。

## 7. 状态机

**工作空间**（desired × observed）：
- `running/running` 正常；`running/stopped` → 对账补 start；`stopped/running` → 对账补 stop；失败 → `error` + error_code。

**操作**（state）：`queued → running(lease_owner, lease_until) → succeeded | failed`。租约 120 秒超时可被接管；每空间活动操作唯一。

**票据**：未使用 → used_at（单次）；会话撤销时未使用票据被消费，防止旧标签兑换。

## 8. 安全设计

- **认证**：Cookie 会话 + 绝对过期 + 失败限流；OIDC PKCE/JWKS/nonce；TOTP。
- **授权**：`current_identity` 每请求解析角色；`require_platform_admin` / `require_tenant_admin` / `require_permission` 分层；跨租户统一 404。
- **CSRF**：写操作校验 `X-CSRF-Token` 与会话 csrf_hash；edge 层 Origin 校验。
- **签名**：relay 请求 HMAC 绑定 method/path/workspace/generation + 时间戳防重放。
- **机密**：`<NAME>_FILE` secrets；`init-secrets.ps1` 生成；仓库/镜像无明文。

## 9. 威胁模型与缓解（摘要）

| 威胁 | 缓解 |
|---|---|
| 跨租户越权读 | membership 校验 + 统一 404 + 租户管理员限本租户 |
| 票据重放/换绑 | 单次消费 + Host/Origin/epoch 绑定 |
| 路径穿越/符号链接 | dir_fd + O_NOFOLLOW + 组件级校验 |
| 容器逃逸 | 非 root/只读/cap_drop/no-new-privileges/无 docker.sock |
| 跨空间网络渗透 | 独立 internal 网络 + 无外网 + 无默认 bridge |
| 密钥泄露 | secrets 注入 + 日志脱敏 + 扫描门禁 |
| 撤权延迟 | Redis 跨进程广播 + 活跃连接关闭 |

## 10. 可扩展点

`RuntimeDriver` 为抽象接口，`DockerRuntimeDriver` 是当前实现；K8s 需实现同样契约（ensure/start/stop/rebuild/inspect/attach_gateway/credential）即可替换，无需改控制面。
