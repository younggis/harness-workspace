# Harness Workspace 需求文档

版本：v1.0（2026-11-20） · 对应实现：`0cbfd74` 及后续 · 验收记录：`docs/verification.md`

## 1. 背景与目标

面向企业/团队的多租户 AI 开发工作台：管理员在统一控制面分配并管理**隔离的 Linux 工作空间**，用户通过浏览器在各自空间内使用 Agent 对话、文件编辑与交互终端，底层模型调用走统一的模型代理并受预算约束。

核心目标：

- **多租户隔离**：租户之间、空间之间在计算、存储、网络、身份上互相不可见、不可达。
- **开箱即用的开发环境**：基于锁定的上游 dsh 版本，提供一致的运行镜像。
- **企业级身份与治理**：本地账号 / OIDC SSO / MFA / SCIM / 服务账号令牌，细粒度权限与完整审计。
- **可运维**：租约队列、对账、备份恢复、PITR、容量基线、升级门禁。

明确不做：多租户计费系统、K8s RuntimeDriver（预留接口）、SAML/LDAP、真实 IdP 现场联调（待环境）。

## 2. 角色

| 角色 | 说明 |
|---|---|
| 平台管理员（platform admin） | 全局身份，管理所有租户/用户/模板/审计/用量 |
| 租户管理员（tenant_admin） | 在所属租户内管理成员与空间，查看本租户审计/用量 |
| 普通成员（member） | 查看并使用自己拥有的空间，不能进入管理页 |
| 服务账号 / 自动化 | 通过 scoped API token 以限定 scope 调用服务端接口（如 SCIM） |

## 3. 功能需求

### FR-1 身份与认证
- FR-1.1 本地账号：登录名唯一、Argon2id 单向哈希、无默认密码；失败 5 次/300 秒限流。
- FR-1.2 会话：HttpOnly + SameSite=Lax Cookie，绝对过期；登出/租户切换撤销派生会话与票据。
- FR-1.3 OIDC：Authorization Code + PKCE、JWKS 验签、nonce 校验；可配置 JIT 开通。
- FR-1.4 MFA：TOTP 自助 enroll / verify / disable；启用后密码正确仅返回 `mfa_required`。
- FR-1.5 SCIM 2.0：User 资源 CRUD，bearer token 鉴权；停用/删除级联撤销会话。
- FR-1.6 服务账号：`/api/me/tokens` 创建/列举/撤销，12 项 scope 白名单，明文仅返回一次。

### FR-2 租户与授权
- FR-2.0 租户可定义容器资源策略：单空间 CPU/内存/PIDS 规格 + 运行态总量上限；空间继承并可覆盖；受平台硬上限约束（详见 `docs/TENANT_RESOURCES.md`）。GPU 不在本轮范围。
- FR-2.1 用户为全局身份，通过 membership 加入租户并持有角色；同一用户可属于多个租户。
- FR-2.2 空间归属于「租户 + 该租户成员」。
- FR-2.3 两级角色 + 11 项细粒度权限（`tenant/user/member/workspace/usage/audit/template` 读写）；平台管理员全通过、租户管理员 8 项、成员仅 `workspace:read`。
- FR-2.4 跨租户资源一律返回统一 404，不泄露存在性。

### FR-3 工作空间生命周期
- FR-3.1 分配：租户管理员在配额内创建空间，绑定模板。
- FR-3.2 动作：start / stop / rebuild / disable / enable，带 `Idempotency-Key`；相同 key 不同参数返回 409。
- FR-3.3 租约队列：操作入队、租约领取、超时接管；每空间同时只有一个活动变更。
- FR-3.4 对账：期望态与实际态不一致时自动补操作；relay/llm 网关服务重建后自动重挂。
- FR-3.5 重建挂载原卷，保留文件；generation/auth_epoch 递增并吊销旧凭据。
- FR-3.6 停用/停止在 3 秒内关闭该空间全部活跃 WS/终端/SSE 连接。

### FR-4 空间接入网关
- FR-4.1 一次性 entry ticket：仅空间所有者/管理员可创建，短 TTL，单次兑换。
- FR-4.2 兑换校验：portal Origin、Host 绑定、epoch、会话状态；成功后下发空间会话 Cookie。
- FR-4.3 代理链路：浏览器 → edge → API 网关 → 空间内适配器 → dsh；平台凭据不下传 dsh。
- FR-4.4 实时通道：终端/SSE 走 WebSocket 网关，签名转发到 relay。

### FR-5 空间内能力
- FR-5.1 Agent 对话：真实 DeepSeek 模型，流式响应，记录 token 用量与缓存命中。
- FR-5.2 文件：列表/上传/下载/删除/建目录/移动；路径穿越、符号链接、设备文件拒绝；ETag 版本冲突 412；单文件上限 128 MiB。
- FR-5.3 终端：PTY WebSocket，交互式 shell。

### FR-6 治理与运维
- FR-6.1 审计：身份、空间、票据、成员、模型调用等关键动作全部记录。
- FR-6.2 用量：按租户/模型统计 token 与预算桶。
- FR-6.3 备份/恢复/PITR：脚本化演练并留痕。
- FR-6.4 容量基线、升级门禁、密钥扫描。

## 4. 非功能需求

| 编号 | 类别 | 要求 |
|---|---|---|
| NFR-1 | 隔离 | 每空间独立容器 + 卷 + **内部专用 Docker 网络**，绝不接默认 bridge；无宿主 PG、无 Docker socket、无外网、无跨空间可达 |
| NFR-2 | 加固 | 非 root(10001)、只读根文件系统、`cap_drop=ALL`、`no-new-privileges`、tmpfs noexec、pids/内存/CPU 限额 |
| NFR-3 | 机密 | 仅 `.env.local` / Docker secrets；镜像与仓库无明文密钥；`<NAME>_FILE` 注入 |
| NFR-4 | 传输 | 生产 HTTPS + HSTS；开发自签名证书仅用于联调 |
| NFR-5 | 可靠性 | 操作幂等、租约接管、对账自愈、日志轮转、重启策略 |
| NFR-6 | 可观测 | 统一错误包络 + request_id；健康探针 live/ready |
| NFR-7 | 兼容性 | Windows 11 + Docker Desktop(Linux)；仅操作 PG 的 harness/harness_test schema |

## 5. 验收映射（手册第 12 节 T01–T17）

| 项 | 内容 | 状态 |
|---|---|---|
| T01–T09 | 引导/迁移/身份/租户/空间/票据/文件/终端/对话 | 通过（`docs/verification.md` 1.1–1.14、1.28） |
| T10–T14 | 会话/隔离/RBAC/审计/完整业务链 | 通过（同上，含 1.23 隔离渗透） |
| T15 | 备份恢复 / PITR | 通过（1.16 / 1.22） |
| T16 | 生产 HTTPS + secrets / 多副本撤权 | 实现与静态验证通过（1.20 / 1.21） |
| T17 | 完整压测 | **部分**（容量基线已采集；冷/热启动 ×5 与 1/2/4 空间并发待专用环境） |

## 6. 待验证（需环境/授权，非需求缺失）

真实 IdP 联调、受信任 CA 证书端到端、现有 Windows PG 主从/归档配置、第三方渗透测试与 SOC2/DPA 合规材料、T17 完整压测。

## 7. 极端条件验收补充（本轮）

见 `docs/verification.md` 1.29：认证滥用、畸形输入、跨租户越权、票据重放/Origin/Host 绑定、文件服务路径穿越/符号链接/ETag/超限、跨空间网络隔离。共 26 项离线测试 + 19 项容器内真实探针 + 4 项真实网关异常检查全部通过。
