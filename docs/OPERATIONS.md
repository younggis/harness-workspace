# Harness Workspace 操作文档（Runbook）

版本：v1.0（2026-11-20） · 面向管理员与运维的日常操作、故障排查、应急

## 1. 日常用户流程

1. 打开 `http://portal.127.0.0.1.nip.io:8080` → 账号密码登录（企业 SSO 配置后也可“使用企业账号登录”）。
2. 工作台选择租户 → 在“我的工作空间”点“进入工作空间”。
3. 空间内：左侧会话列表可新建/切换；输入框发送消息调用真实 DeepSeek；文件面板上传/下载/删除；顶部打开交互终端。
4. 右上角用户菜单：切换租户、安全设置（MFA 自助 enroll/确认/关闭）、退出登录。

## 2. 管理员操作（管理页）

- **租户**：新建、停用、改配额（running/workspace 上限、日 token 预算）。
- **用户**：新建、重置密码、禁用/启用、设平台管理员。
- **成员与空间**：先选租户 → 成员列表设角色（tenant_admin/member）与状态 → 工作空间列表分配/启停/重建。
- **用量与审计**：查看事件链与 token 消耗。

RBAC 约束：成员看不到“管理”菜单；租户管理员仅能管本租户；跨租户资源统一 404。

## 3. 健康检查（每次交接/巡检）

```powershell
curl http://127.0.0.1:8080/health/live
curl http://127.0.0.1:8080/health/ready
docker compose --env-file .env.local -p harness-local-dev ps
docker ps --format '{{.Names}} {{.Status}}' | Select-String 'rt-'
```
DB 版本与计数：
```powershell
psql -h 127.0.0.1 -U postgres -d postgis -c "select version_num from harness.alembic_version;"
```

## 4. 常见运维动作

| 场景 | 操作 |
|---|---|
| 空间卡住 / 实际态错误 | 确认 desired/observed；在管理页 rebuild（挂原卷）；worker 每 15s 对账自愈 |
| 网关服务重建后断连 | worker 对账自动 `attach_gateway` 重挂 relay/llm；无需手工 |
| 会话泄露 / 人员离职 | 管理页列会话 → 吊销；空间动作 stop/disable 在 3s 内关闭活跃连接 |
| token 泄露 | `DELETE /api/me/tokens/{tid}` 或重新签发；SCIM 停用用户级联撤会话 |
| 配额调整 | 管理页改租户 max_running / max_workspaces / daily_token_budget 及 CPU/内存/PIDS 单空间规格与总量上限（下调总量不得低于当前用量，新配额在下次 start/rebuild 生效） |
| Docker 报 `all predefined address pools have been fully subnetted` | 历史遗留孤立空间网络耗尽地址池；worker 现在每 5 分钟自动 GC，紧急时可 `.\scripts\cleanup-space-networks.ps1`（dry-run）确认后加 `-Apply` |
| 快速连续点停止/启动返回 409 | 同一空间同时只允许一个活动操作；等当前操作完成后重试 |
| 写请求仅带 Cookie 报 `Invalid CSRF token` | CSRF 已强制 `X-CSRF-Token` 头（不再回退 Cookie）；前端会自动带，API 调用方需显式提供 |
| 轮换签名密钥 | `scripts/rotate-secrets.ps1` 打印新值；先设 `SESSION_SIGNING_KEY_PREVIOUS=<旧>` 并替换 `SESSION_SIGNING_KEY`，重启；一个窗口后去掉 PREVIOUS 再重启。`HARNESS_WORKSPACE_TOKEN_SEED` 轮换需 rebuild 全部空间 |
| 审计/模型记录增长 | 定期运行 `.\scripts\prune-history.ps1`（先 dry-run 看数量，再 `-Apply`）；按 `.env.local` 的 `AUDIT_RETENTION_DAYS` / `MODEL_REQUEST_RETENTION_DAYS` 删除 |
| Docker 地址池耗尽 | worker 每 5 分钟自动 GC；若仍耗尽，按 `infra/docker/daemon.json` 扩展 Docker 地址池并重启 Docker |
| 撤销后旧标签 | 切换租户/登出会消费未用票据并撤销派生会话 |

## 5. 隔离与加固巡检

在每个运行时容器内执行：
```powershell
Get-Content scripts\runtime_isolation_probe.py | docker exec -i <runtime-cid> python3 -
Get-Content scripts\fileservice_probe.py     | docker exec -i <runtime-cid> python3 -
```
期望：`ISOLATION_PASS`、`FILESERVICE_PROBE_PASS`（19/19）。
确认运行时只挂内部专网且 ExtraHosts 正确：
```powershell
docker inspect <runtime-cid> --format '{{json .HostConfig.ExtraHosts}}'
docker inspect <runtime-cid> --format '{{json .NetworkSettings.Networks}}'
```

## 6. 备份 / 恢复 / PITR

```powershell
.\scripts\backup.ps1
.\scripts\restore.ps1 -BackupFile <file>       # 隔离演练，使用 PG_ADMIN_* 仅演练
.\scripts\pg-pitr-drill.ps1
```
演练结果记录：`BACKUP_OK` / `RESTORE_OK` / `PITR_DRILL_PASS`。生产恢复前务必在隔离 schema 演练。

## 7. 审计与用量

- 平台审计：`GET /api/admin/audit`；租户审计：`GET /api/admin/tenants/{tid}/audit`。
- 用量：`GET /api/admin/tenants/{tid}/usage`；DB 表 `model_requests`/`budget_buckets`。
- 关键动作（登录、票据、空间动作、成员变更、MFA、SCIM、token）均含 `request_id`。

## 8. 故障排查表

| 现象 | 可能原因 | 处理 |
|---|---|---|
| 进入空间 `Internal Server Error` | 隔离网无 DNS，适配器无法解析公网 authority | 确认 runtime `ExtraHosts` 含 `w-<uuid>...:127.0.0.1`；重建 worker 触发对账重建 |
| 进入空间 `WORKSPACE_NOT_READY` | observed 非 running / 对账未完成 | 等待 ≤15s 或检查 worker 日志与 operations 表 |
| `Origin check failed` | 请求的 Origin 与 PORTAL_ORIGIN 不一致 | 浏览器走正确域名；API 调用带正确 Origin |
| `Invalid CSRF token` | 缺少/不匹配 X-CSRF-Token | 从 `/api/me` 取最新 csrf 并重放请求 |
| `FORBIDDEN` on admin | 角色非平台/租户管理员 | 用管理员账号或检查 membership 角色 |
| 普通成员看到“管理”菜单 | 旧前端缓存 / role 未返回 | 确认 `/api/me` tenants 含 role；硬刷新清缓存 |
| 未登录点“工作台”报“无权限” | 旧前端缓存（含缺失的路由守卫） | 硬刷新加载新 bundle；`/` 应自动跳 `/login`；顶部不应显示“工作台” |
| 启动/停止报 `crypto.randomUUID is not a function` | 旧前端 bundle；HTTP nip.io 非安全上下文 | 硬刷新加载新 bundle（`newId()` 有 getRandomValues 回退） |
| 登录 `RATE_LIMITED` | 5 次/300s 失败 | 等待窗口过期或换账号；检查是否口令错误 |
| 票据 `Invalid or expired ticket` | 重放/过期/会话撤销 | 重新从工作台进入生成新票据 |
| WS 终端连不上 | Host/Origin 不匹配或网关未挂 | 用空间域名访问；检查 relay 入网与 worker 对账 |

## 9. 安全事件响应

1. 立即吊销涉事 `AuthSession`（管理页）与所有 API token、`SCIM` 停用用户。
2. stop/disable 相关空间，关闭活跃连接。
3. 导出审计（`/api/admin/audit`）留证。
4. 检查 `docs/verification.md` 与探针结果确认隔离未被突破。
5. 轮换签名密钥（`RELAY_SIGNING_KEY`/`SESSION_SIGNING_KEY`）并重启控制面（将使现有会话失效）。

## 10. 脚本索引

`up.ps1` / `down.ps1` / `build.ps1` / `doctor.ps1` / `migrate.ps1` / `admin-create.ps1` /
`init-local.ps1` / `init-secrets.ps1` / `gen-devcert.ps1` / `test.ps1` /
`backup.ps1` / `restore.ps1` / `pg-pitr-drill.ps1` / `capacity-baseline.ps1` /
`upgrade-check.ps1` / `runtime_isolation_probe.py` / `fileservice_probe.py`。

## 11. 待验证（需环境/授权）

真实 IdP 联调、受信任证书 HTTPS、现有 Windows PG 主从/归档配置、第三方渗透测试与合规、T17 完整压测。
