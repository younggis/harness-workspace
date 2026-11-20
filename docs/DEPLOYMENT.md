# Harness Workspace 部署文档

版本：v1.0（2026-11-20） · 面向开发/验收/生产形态

## 1. 前置条件

- Windows 11 + Docker Desktop（Linux 容器，当前实测 29.9.2）。
- 宿主已有 PostgreSQL（实测 12.2，`127.0.0.1:5432/postgis`）；**仅使用 `harness`/`harness_test` 专用 schema**，不改 public/GIS 表、不改其他 Docker 项目。
- Python 3.11 venv、Node/pnpm（前端构建）、DeepSeek API key。
- 浏览器域名解析：`portal.127.0.0.1.nip.io`、`w-<uuid>.127.0.0.1.nip.io`（回环 DNS）。若本机 Chrome 对 `*.localhost` 解析异常，用 nip.io；代理需把 `*.127.0.0.1.nip.io` 加入「不使用代理」。

## 2. 本地开发部署（PowerShell）

```powershell
Copy-Item .env.example .env.local
.\scripts\init-local.ps1                      # 生成签名密钥；交互式输入 postgres 口令
psql -h 127.0.0.1 -U postgres -d postgis -W -f .\db\bootstrap.psql   # 仅建专用角色
.\scripts\doctor.ps1                          # 环境体检
.\scripts\build.ps1                           # 构建 api/worker/relay/llm/edge/front + runtime 镜像
.\scripts\migrate.ps1                         # Alembic upgrade head
.\scripts\admin-create.ps1                    # 交互式创建首个管理员（无默认密码）
.\scripts\up.ps1                              # 启动 5 个控制面容器
```

验证：
```powershell
curl http://127.0.0.1:8080/health/live     # 200
curl http://127.0.0.1:8080/health/ready    # {"status":"ok",...}
docker compose -p harness-local-dev ps
```

浏览器打开 `http://portal.127.0.0.1.nip.io:8080`。

**端口**：edge 8080（开发）。防火墙只监听 loopback。

## 3. 生产形态（HTTPS + Docker Secrets）

```powershell
.\scripts\init-secrets.ps1                    # 从 .env.local 生成 secrets/*.txt（gitignore）
.\scripts\gen-devcert.ps1                     # 仅自签名开发证书；生产替换为受信任 CA
# 修改 .env.local: PORTAL_ORIGIN=https://<域名>:8443, WORKSPACE_HOST_SUFFIX=.<域名>:8443
docker compose --env-file .env.local -p harness-prod -f compose.prod.yaml up -d
```

- 端口：8080（HTTP→HTTPS 跳转）、8443（TLS）。真实 LB 可把 443 映射到 8443。
- Secrets：`pg_app_password`、`relay_signing_key`、`session_signing_key`、`workspace_token_seed`、`oidc_client_secret`、`scim_bearer_token` 以 `_FILE` 注入 `/run/secrets/`。
- 加固：资源限制、日志轮转（20m×5）、`restart: unless-stopped`、控制面内部网无外网。
- **待验证**：受信任证书端到端、443/域名（当前仅自签名且 8080 被开发栈占用）。

## 4. 数据库引导与迁移

- 引导角色：`bootstrap.psql` 创建 `harness_owner`（DDL）、`harness_app`（DML）、`harness_llm`（用量）及测试角色。
- 迁移：`migrate.ps1` 对 `harness` 与 `harness_test` 均执行 `alembic upgrade head`，当前版本 `0006_api_tokens`。
- 维护者凭证 `PG_ADMIN_USER/PASSWORD` 仅用于隔离恢复演练，不用于日常运行。

## 5. 网络与 DNS 拓扑

| 网络 | 类型 | 成员 |
|---|---|---|
| `front` | bridge | edge, api |
| `backend` | bridge | api, relay, llm, worker |
| `control` | internal | api, relay, llm（无外网） |
| 每空间 `net-<ws>-g<n>` | **internal** | 该空间运行时 + 按需挂入的 relay/llm |

- 运行时容器**只在**空间内部网创建（`driver._container_config`），绝不接默认 bridge。
- `extra_hosts` 把公网 authority 钉到 127.0.0.1，适配器用同一 authority 访问 dsh。
- 验证：`docker inspect <runtime> --format '{{json .HostConfig.ExtraHosts}}'` 与 `.NetworkSettings.Networks`。

## 6. 升级与回滚

1. 设置 `DSH_VERSION=<新版本>`。
2. `.\scripts\upgrade-check.ps1 -Version <新版本>`（构建候选镜像 + 版本校验 + 契约/离线测试）。
3. 契约对比：临时空间跑 `capture_contracts.py` / `capture_session_contract.py`，差异需更新适配器。
4. `POST /api/admin/templates` 注册新模板（旧模板保留）。
5. 逐空间 rebuild（挂原卷），验证会话/文件恢复。
6. 回滚：切回旧模板版本并 rebuild。

详见 `docs/upgrades.md`。

## 7. 容量与资源

- 单空间模板：1 CPU / 1 GiB / pids 256（见模板表）；租户可声明自己的单空间规格与运行态总量上限（CPU/内存/PIDS），空间继承并可覆盖，受 `limits.py` 平台上限约束，详见 `docs/TENANT_RESOURCES.md`。GPU 不在本轮范围。
- 容量基线快照见 `docs/capacity.md`（宿主 16 核/31 GB，开发态每空间约 300 MiB）。
- **T17 完整压测待专用环境**：冷/热启动 ×5、1/2/4 空间并发。
- **Docker 地址池**：空间很多时默认池会耗尽（`all predefined address pools have been fully subnetted`）。把 `infra/docker/daemon.json` 的 `default-address-pools` 合并进 Docker Desktop → Settings → Docker Engine 并重启；注意已有网络不会迁移，先备份。worker 每 5 分钟自动 GC 孤立网络。
- **历史数据保留**：`AUDIT_RETENTION_DAYS` / `MODEL_REQUEST_RETENTION_DAYS`（默认 90 天）；定期运行 `.\scripts\prune-history.ps1 -Apply`（先 dry-run 确认数量）。
- **监控**：`docker compose -p harness-monitoring -f compose.monitoring.yaml up -d` 启动 Prometheus(9090)/Grafana(3001)，抓取 API `/metrics` 与 LLM `:8090/metrics`；告警规则在 `infra/monitoring/alerts.yml`。
- **CI**：本地 `.\scripts\ci.ps1`（密钥扫描+测试+构建+配置校验）；GitHub Actions 见 `.github/workflows/ci.yml`。
- **定时备份**：`.\scripts\schedule-backup.ps1 -BackupRoot <共享目录>` 默认 dry-run；确认后加 `-Install`（创建 Windows 计划任务，需管理员权限/操作员授权）。

## 8. 备份/恢复/PITR

脚本：`scripts/backup.ps1`、`restore.ps1`、`pg-pitr-drill.ps1`。演练结果：`BACKUP_OK` / `RESTORE_OK` / `PITR_DRILL_PASS`（见 `docs/verification.md`）。

## 9. 部署后验收清单

- [ ] health live/ready 200/ok
- [ ] 迁移版本 `0006_api_tokens`
- [ ] 首个管理员可登录
- [ ] 空间可分配、启动、进入；三空间隔离探针 PASS
- [ ] 真实模型对话返回响应
- [ ] 文件与终端可用
- [ ] 审计/用量有记录
- [ ] 密钥扫描无泄露

## 10. 已知待验证（非部署缺陷）

真实 IdP、受信任证书、现有 Windows PG 主从/归档（需改 `postgresql.conf` 并重启，属系统级变更，需授权）、第三方渗透测试与合规材料、T17 完整压测。
