# 多租户 Web Harness（本地首版）

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

- **浏览器访问**：`http://portal.localhost:8080`
- **空间域名**：`http://w-<uuid>.localhost:8080`（`*.localhost` 不生效时按 `docs/verification.md` 写 hosts，代理直连）
- **首个管理员**：由 `.\scripts\admin-create.ps1` 交互式创建，无内置默认密码。
  本地开发库中已按此方式创建账号 `admin`（口令仅保存在维护者处）。

## 测试

```powershell
.\scripts\test.ps1 -Suite offline       # 22 passed，无需密钥/Docker
.\scripts\test.ps1 -Suite integration   # 真实 Docker + PG（需 HARNESS_INTEGRATION=1）
.\scripts\test.ps1 -Suite e2e           # 真实浏览器（需 HARNESS_E2E=1）
.\scripts\test.ps1 -Suite live          # 真实 DeepSeek（需有效密钥，产生费用）
.\scripts\test.ps1 -Suite offline       # runtime/worker/gateway 改动后重跑 T03–T13
```

## 当前验收状态（摘要）

- ✅ 真实 PG 引导、迁移（14 张表，0001_init）、管理员创建、容器→宿主认证登录
- ✅ 离线 22 项通过（身份/租户/隔离/票据/幂等/配额/对账/签名）
- ⚠️ 真实 DeepSeek 探针返回 401（提供的密钥无效）→ live 与 T14 Agent 真实生成待验证
- ✅ runtime 镜像已构建（`dsh --version=0.2.2-rc.4`）；浏览器实测登录、租户/空间分配、
  容器启动、票据兑换、三点 GeoJSON 上传下载、xterm 终端 echo 与读同一文件（COUNT 3）
- ⚠️ DeepSeek 真实 Agent 生成 `result.json`、A2/B1 越权、停用后终端关闭、备份恢复与容量基线待验证
  详见 `docs/verification.md` 第 1.7 / 2.1 节与第 4 节 T01–T17。

## 本次现场验证使用的本地地址
`http://portal.127.0.0.1.nip.io:8080`（`portal.localhost` 在本机 WinINET 下解析失败，改用回环 DNS，未改 hosts）。
若本机启用了系统代理，需把 `portal.localhost;*.localhost;portal.127.0.0.1.nip.io;*.127.0.0.1.nip.io`
加入代理的「不使用代理」列表，否则 Chrome 会把这些 Host 发给代理而打不开；
改动位置与验证见 `docs/verification.md` 第 2.3 节。

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
