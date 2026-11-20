# 验收记录（持续更新）

> 规则：只记录**实际执行过**的命令与结果；未运行的一律标记「待验证」；离线、真实
> Docker/PostgreSQL、浏览器 E2E、真实 DeepSeek 四类结论严格区分，不用 Mock 代替集成结论。

## 0. 环境与版本（已实测 2026-11-18）

| 项 | 实测值 | 证据 |
|---|---|---|
| OS | Windows 11 / PowerShell 5.1 | `$PSVersionTable.PSVersion` |
| Docker | 29.9.2, Compose v5.6.1, `linux/amd64`, overlayfs | `docker info` |
| Docker 状态 | daemon 正常；已有 13 容器 / 13 镜像（含 `db-studio-*`、`python_backend-*`，**全程未改动**） | `docker ps -a` |
| Python | 3.12.0（本地 `.venv`） | `python --version` |
| Node / pnpm | v26.13.0 / 10.33.0（镜像内用 corepack 固定 pnpm 11.28.5） | `node -v`, `pnpm -v` |
| PostgreSQL | Windows 服务 PID 11588，`127.0.0.1:5432/postgis`，**PostgreSQL 12.2** | psql `select version()` |
| psql.exe | `C:\Program Files\QGIS 3.44.8\bin\psql.exe`（不在 PATH） | 文件搜索 |
| F: 可用空间 | 约 1.3 GB（注意：npm/node_modules 未在本地安装） | `Get-PSDrive F` |
| 上游 | `deepseek-ai/deepseek-harness` MIT，release `dsh-v0.2.2-rc.4` → `3f321d32…`，master `ca33fd68…`（2026-11-17） | GitHub API，见 `upstream.lock.json` |

## 1. 已执行且通过

### 1.1 真实 PostgreSQL 专用 schema 引导（通过）
```
psql -h 127.0.0.1 -U postgres -d postgis -W -f .\db\bootstrap.psql
```
结果：`harness_owner` / `harness_app` / `harness_llm` 三个非超级用户角色 + `harness`
schema（owner=harness_owner）创建成功；未修改 `public`、未安装扩展、未授权 PUBLIC。
随后仅对这三个专用角色设置口令。复核：
`select rolname from pg_roles where rolname like 'harness%'` → 3 行；
`select nspname,pg_get_userbyid(nspowner) from pg_namespace where nspname like 'harness%'` → 1 行。

### 1.2 真实迁移（通过，含一次缺陷修复）
```
python -m alembic -c migrations/alembic.ini upgrade head
```
首次执行后 `harness` schema 表数为 0——定位为 `SET search_path` 显式开启事务导致
Alembic 只提交 savepoint，外层回滚。修复：`migrations/env.py` 在 `SET search_path`
后 `connection.commit()`。修复后复核：
- `harness.alembic_version` = `0001_init`
- `harness` schema 共 14 张表（13 业务表 + alembic_version）
- `public` 仍为原有 3 张 PostGIS 表，`app` schema 的既有表未变动

### 1.3 首个平台管理员（通过）
```
python services\api\cli.py admin-create     # 交互式；脚本化用 HARNESS_ADMIN_LOGIN/PASSWORD
```
结果：`harness.users` → `admin | t | active`。无内置默认口令。

### 1.4 容器 → 宿主 PostgreSQL 真实登录（通过）
```
docker run --rm --add-host=host.docker.internal:host-gateway -e PGPASSWORD=*** `
  postgres:12-alpine psql -h host.docker.internal -p 5432 -U harness_app -d postgis -w `
  -c "select current_database(),current_user,inet_client_addr();"
```
结果：`postgis | harness_app | 127.0.0.1`。不只是 TCP 通，认证与解析均通过。

### 1.5 离线测试（通过）
```
.\.venv\Scripts\python.exe -m pytest tests/ -q
```
结果：**22 passed**。覆盖：Argon2id、CSRF/Origin、relay 签名绑定与过期、登录限流与通用
错误、租户/成员越权、幂等分配与配额、操作幂等与冲突、跨租户隔离、切租户吊销、
disable 关闭入口、票据单次消费与 Host 绑定、worker 租约领取/处理/对账。

### 1.6 上游版本锁定（已核实）
`upstream.lock.json` 中的源码 URL、MIT、release tag/commit、npm 包版本、Node/pnpm 要求、
Web 默认端口 3080、启动参数、代理与模型配置来源均取自 GitHub API 与锁定 tag 的文档；
`contracts/upstream/README.md` 标记 `PENDING_M0_E2E`（未捕获真实事件样本，禁止臆造）。

### 1.7 真实浏览器 + 容器全链路（通过，2026-11-18 现场）

Docker Hub 恢复后重新构建成功，并在浏览器实测：

```
docker pull node:24-bookworm-slim
docker build -t harness-runtime-base:0.2.2-rc.4 -f runtime/base/Dockerfile .
docker compose --env-file .env.local -p harness-local-dev build api relay llm worker
docker compose --env-file .env.local -p harness-local-dev up -d
```

- 镜像内 `dsh --version` = **0.2.2-rc.4**（锁定版本实测）。
- `portal.localhost` 在本机不解析 → 按手册第 3 节改用 `portal.127.0.0.1.nip.io:8080`
  与 `w-<uuid>.127.0.0.1.nip.io:8080`（公网 DNS 回环，未改 hosts）。
- 浏览器 `http://portal.127.0.0.1.nip.io:8080/login` 用 `admin` 登录 → 200，`/api/me` 200。
- 通过真实受保护 API 创建租户 A、用户 TA/A1、成员关系、模板 `base-v1`、A1 空间。
- A1 登录后 `POST /api/workspaces/{wid}/actions/start` → 操作 `succeeded`、
  `observed_state=running`；worker 实际创建带标签的 runtime 容器、双卷、专网。
- 一次性票据 `POST /api/workspaces/{wid}/entry-tickets` → `POST /_platform/enter`（门户精确
  Origin，携带 workspace Host）→ 303 到空间 Host，空间 Cookie 生效；浏览器侧收不到平台 Cookie。
- 空间 Host 的文件链路：`PUT /_platform/file?path=points.geojson` → 200 + ETag
  `e486d9df…`；`GET` 返回同一 ETag，`features.length = 3`；`GET /_platform/files` 列出该文件。
- 空间 Host 的 WS 终端：浏览器 xterm 显示「已连接」；另用真实 WS 客户端（新票据兑换的
  Cookie、精确 Host/Origin）发送 `echo HARNESS_OK` 得到回显，并读取同一个
  `/workspace/points.geojson` 得到 `COUNT 3`。
- 期间定位并修复的真实缺陷：nginx 在 `if` 中使用 `proxy_http_version` 导致 502；
  workspace Host 的 `/_platform/ui/*`、`/assets/*`、`/index.html` 静态资源路由；
  relay 丢失 query string；runtime 网络别名未生效；`fileservice.write_file` 新建文件误抛
  `FileNotFoundError`；WS 路由依赖注入导致 403；"最后租户管理员"守卫误拒普通成员；
  gateway/relay 重建后对账重连。修复后全部复跑通过，离线 22 项仍全绿。

> 上述为**真实 Docker + PostgreSQL + 浏览器/WS** 集成，不是 Mock。
> DeepSeek 真实 Agent 生成 `result.json` 仍未通过（见 2.1 密钥 401）。

## 2. 已执行但失败 / 阻塞

### 2.1 真实 DeepSeek 调用（失败：凭据无效）
```
python scripts\deepseek_smoke.py     # 读取 .env.local 的 DEEPSEEK_API_KEY
```
结果：HTTP **401**，`Authentication Fails, Your api key: ****322d is invalid`，
`request_id: 55ec7e25-3897-471a-ad5b-4142dfa6632e`。
结论：用户提供的密钥被上游拒绝。**live 套件（T09 live、T13 live、T14 Agent 真实生成）
为「待验证」**，需更换有效密钥后重跑：
```
# 更新 .env.local 中 DEEPSEEK_API_KEY，然后
.\scripts\test.ps1 -Suite live
```
密钥仅写入 gitignore 的 `.env.local`，未进入任何 fixture、报告或 committed 文件。

### 2.2 runtime 镜像构建（历史失败，已恢复）
```
docker build -t harness-runtime-base:0.2.2-rc.4 -f runtime/base/Dockerfile .
```
两次均在 `#2 load metadata for node:24-bookworm-slim` 失败：
`failed to fetch anonymous token ... dial tcp [2a03:2880:f12a:83:...]:443: connectex ...`。
本机缓存有 `python:3.12-slim`、`nginx:alpine`，但无 Node 24 镜像；控制面镜像可构建，
runtime（依赖 dsh 的 Node ≥24.9）需先解决 Docker Hub 访问。未使用未锁定的 npx 绕过。
`upstream.lock.json` 的 `base_digest` 保持 `PENDING_M0_BUILD_RECORD`。

## 3. 未执行（明确「待验证」）

| 项 | 原因 | 可复跑命令 |
|---|---|---|
| runtime 镜像构建 | **已完成**：Docker Hub 恢复后 `node:24-bookworm-slim` 拉取成功，镜像构建完成，`dsh --version=0.2.2-rc.4` | `docker build -t harness-runtime-base:0.2.2-rc.4 -f runtime/base/Dockerfile .` |
| 原生 dsh Web 启动、根路径 token→cookie 交换、WS 升级与断线续连 | 依赖上一项镜像 | `.\scripts\up.ps1` 后在浏览器打开空间 Host |
| 浏览器 E2E（T04/T07/T08/T14 的网页部分） | **部分通过**：浏览器登录、票据兑换、文件页、xterm 连接已实测；完整自动化脚本未跑 | `$env:HARNESS_E2E=1; .\scripts\test.ps1 -Suite e2e` |
| 真实 Docker/PG 集成套件 | 测试 schema 角色口令尚未交互式设置；未启动栈 | 先 `psql -f db\bootstrap_test.psql` + `\password`，再 `$env:HARNESS_INTEGRATION=1; .\scripts\test.ps1 -Suite integration` |
| 前端 `pnpm run build` | 本地 F: 仅 1.3 GB，未安装 node_modules | 在 `apps/portal` 执行 `pnpm install && pnpm run build` |

## 4. 第 12 节逐项状态

| 编号 | 结果 | 说明 |
|---|---|---|
| T01 P0 环境 | **部分通过 / 待验证**：PG 引导、迁移、管理员、容器登录通过；重复启动两次与干净检出未跑 | `doctor.ps1` / `up.ps1` 两次 |
| T02 P0 角色 | **离线通过**：TA 越权 B 返回 404、P 无文件权限、切租户吊销旧链接；UI 隐藏按钮之外的后端断言已覆盖 | `pytest tests/test_control_plane.py` |
| T03 P0 隔离 | **离线通过**：跨空间 workspace/operation 统一 404；WS/终端真实隔离待集成 | 同上 + `test_worker.py` |
| T04 P0 入口票据 | **离线通过**：单次消费、过期、错 Host、Origin 校验；原生上游直达与退出重开待 E2E | `test_entry_ticket_single_use_and_host_binding` |
| T05 P0 并发配额 | **离线通过**：同键同参同操作、同键异参 409、重复分配幂等；10 并发与最后名额待集成 | `test_workspace_action_idempotency_and_conflict` |
| T06 P0 网络/权限 | **部分通过**：容器→宿主 PG 认证通过；runtime 非 root/cap/mount 断言已写入集成套件，未实跑 | `tests/integration/test_docker.py` |
| T07 P0 文件 | **集成通过（部分）**：浏览器/HTTP 真实上传三点 GeoJSON，PUT/GET ETag 一致，`features.length=3`，目录列表可见；父目录/符号链接/并发 412/128 MiB 边界未逐项跑 | 见 1.7；E2E 边界用例 |
| T08 P0 终端 | **集成通过（部分）**：浏览器 xterm 显示「已连接」；真实 WS 客户端 `echo HARNESS_OK` 回显、读取同一文件 `COUNT 3`；Ctrl+C/resize/3 秒停用关闭待跑 | 见 1.7；E2E 用例 |
| T09 P0 模型 | **通过**：真实 DeepSeek 流式 + 工具调用往返，容器实际写出文件（见 1.8） | 浏览器实测 + `test.ps1 -Suite live` |
| T10 P0 审批/取消 | **代码完成 / 待验证**：dsh 原生审批复用，前端未接真实事件 | M0 事件样本缺失 |
| T11 P0 恢复 | **部分通过**：卷/代际/凭据撤销模型已实现；强停 runtime 与会话恢复待集成 | T11 E2E |
| T12 P0 故障 | **代码完成 / 待验证**：worker 租约接管、对账、失败释放名额已离线测试；Desktop/DB 失联待集成 | `test_worker.py` |
| T13 P0 模型异常 | **代码完成 / 待验证**：401/429/超时/中断/缺 usage 分类与预算预留已实现；真实多空间预算待 live | `tests/live` |
| T14 P0 完整业务 | **通过**：分配→登录→票据→Agent 写出 result.json（count=3，bbox 精确匹配）→网页查看→文件 API/终端可读；A2/B1 越权与停用关闭仍待验证 | 见 1.8 |
| T15 P0 运维交付 | **待验证**：`backup.ps1`/`restore.ps1 -Target test` 已交付，恢复演练未跑 | 手工演练 |
| T16 P0 日志与内容 | **代码完成 / 待验证**：脱敏、无敏感 CORS、下载 nosniff 已实现；合成标记扫描待跑 | 集成后扫描 |
| T17 基线 容量 | **待验证**：需真实栈 | 冷/热启动各 5 次 |

### 2.3 本机 Chrome 打不开链接（已定位并修复）
现象：Chrome 打开 portal 链接失败、进入空间接口报错。根因：Windows 代理
`127.0.0.1:7890` 已启用，其 `ProxyOverride` 只含 `localhost`、`127.*`，不含
`portal.localhost` / `*.nip.io`，Chrome 把这两个 Host 发给代理导致失败；
`curl --noproxy '*'` 对全部 Host 均 200，证明服务本身正常。
处置：在 `HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings`
的 `ProxyOverride` 末尾追加 `portal.localhost;*.localhost;portal.127.0.0.1.nip.io;*.127.0.0.1.nip.io`
并调用 `InternetSetOption` 刷新 WinINET（可随时从该注册表值删回）。
另外 `portal.localhost` 在 WinINET 下 DNS 解析失败，故本机统一使用
`http://portal.127.0.0.1.nip.io:8080`。复测（走 WinINET 代理，同 Chrome）：
登录 200 → 票据 201 → `/_platform/enter` 303 + Set-Cookie，门户 200、空间 UI 200。

### 2.4 工作空间根路径 `/` 报 `{"raw":"Internal Server Error"}`（已修复）
用户直接在浏览器打开空间根路径报 500。逐层定位并修复了 6 个真实缺陷：
1. **dsh 进程根本没起来**：`dsh` 原生插件加载器会把 `.node` 复制到 `/tmp` 再 `dlopen`，
   而 runtime 的加固 tmpfs 是 `noexec` → `failed to map segment`。
   修复：容器注入 `NARB_DISABLE_NATIVE_CACHE=1`，直接从只读镜像加载插件。
2. **令牌交换打回自身**：适配器用对外 URL 做根路径 token→cookie 交换，在容器内会
   回到自己的 8080 形成回环。修复：改为请求 `127.0.0.1:3080`，仅携带对外 Host。
3. **网关把 HTML 包成 JSON**：`_proxy` 对所有响应做 `_safe_json`，dsh 页面变成
   `{"raw":"..."}`。修复：按 `content-type` 透传原始字节。
4. **静态资源冲突**：dsh 与门户都用 `/assets/...`。修复：门户构建改 `base:'./'`，
   edge 只把 `/_platform/ui/assets/` 指向门户，其余 `/assets/` 走网关到 dsh。
5. **Origin 误判**：dsh 的 `/api/...` 在 workspace Host 上被按门户 Origin 校验 → 403。
   修复：中间件按 Host 是否 `w-` 前缀选择期望 Origin。
6. **原生 WS 未转发**：只有终端 WS 有代理。修复：gateway/relay/runtime 三端增加通用
   WebSocket 转发，携带签名与 dsh Cookie；并修正 worker/Compose 未传递
   `WORKSPACE_HOST_SUFFIX` 导致 dsh 信任域名不匹配的问题。

复测（真实 HTTP + WS 客户端，走完整链路）：
- 根路径 `200`，返回真实 dsh HTML；dsh 原生 `/api/...` `200`（不再 403）
- `ws://w-<uuid>.127.0.0.1.nip.io:8080/api/remote.mux` **connected**
- 浏览器空间根路径标题 `DeepSeek Harness`，控制台 **0 error**
- 离线测试仍 22 passed / 6 skipped

> 注意：直接打开空间根路径但没有票据会话时会得到 **401**（设计如此）。
> 正确入口是从门户点「进入」，由一次性票据兑换空间 Cookie 后跳转。

### 1.8 真实 Agent 对话与 GeoJSON 业务链（通过，2026-11-18）
换用有效密钥后在浏览器实测完整业务链：
- 登录 → 票据 → 进入工作空间 → 选工作区 `web` → 模型 `deepseek-flash`（harness 路由）
- 输入任务「用 Python 标准库统计 points.geojson 的要素数与包围盒并写入 result.json」
- Agent 真实调用 DeepSeek（经 llm 代理与预算表），写出 `count_bbox.py`，执行时因
  `workspace-write` 沙箱拒绝写 `/workspace/result.json`，弹出审批，用户点「允许一次」后
  实际写出文件；最终答案 `{"count": 3, "bbox": [0, 0, 3, 4]}`（与三点 fixture 精确一致）。
- 容器内 `cat /workspace/result.json` = `{"count": 3, "bbox": [0, 0, 3, 4]}`；
  浏览器 `/_platform/file?path=result.json` 返回 200 且同内容，文件列表含两个文件。
- 用量 78.5K tok，5 轮 11 步，249 tok/s，缓存命中 85%。

期间修复的关键缺陷：原生 WS text/binary 帧类型未保留（dsh 要求 text）；SSE 事件流被
网关缓冲导致 500；llm 角色缺 SELECT 权限；`text(sql, params)` 用法错误；`created_at`
非空；令牌被撤销后未轮换；模型 contextWindow 太小导致切换失败；`--patch` 必须是
launcher 标志；`.node` 加载器与 `noexec` tmpfs 冲突；令牌交换回环等。

**结论：T09（真实工具往返）与 T14（浏览器完整业务链）判定通过。**
仍待验证：A2/B1 跨租户越权实测、停用后 3 秒关闭终端、备份恢复演练、容量基线。

### 2.5 更新 DeepSeek 密钥后的对话链路（历史记录，已由 1.8 取代）
用户换用新密钥 `sk-…48152`，实测官方非流式探针 **200**（有真实 request id），
`.env.local` 与 llm 服务已更新；`dsh --dump-config --patch` 确认模型路由已注入：
`llm-pi-ai.providers.harness` → `openai-completions` / `http://model-proxy:8090/v1`，
`agent-default-model.provider=harness`；worker 注入 `HARNESS_MODEL_TOKEN`。
但原生 dsh Web 的 `/api/remote.mux` WebSocket 握手仍被上游以 **401 unauthorized** 拒绝
（见 runtime 适配器 `[adapter-ws] resp=401 body=b'unauthorized'`），页面停留在
「重新连接中 / 正在加载工作区…」，因此**对话仍不可用**。
根因已收敛到上游 dsh 的会话 Cookie/Host/Origin 组合在 WS 握手时不匹配，
不是密钥问题；需要对照锁定版本继续调适配器，或用上游支持的预置工作区/会话接口。
结论：T09/T14 的 Agent 真实生成仍标记「待验证」，不冒充通过。

### 1.9 测试租户 / 登录 / 会话（通过，2026-11-19）
用真实 API 创建 `test-tenant`，以及 `testadmin`(tenant_admin)/`testuser`(member)，口令
（本地 fixture，口令由 `HARNESS_TEST_PASSWORD` 环境变量提供）。复跑：`powershell -File .\scripts\_tenant_test.ps1`。
结果：
- admin 登录 → 创建租户 201、用户 201、成员关系 200
- testadmin 登录 → 200，租户列表 1 个，active_tenant 正确
- `/api/me` 200；同一 Cookie 重复请求返回同一用户（会话保持）
- `/api/auth/logout` 200；此后 `/api/me` → **401**（会话被吊销）
- testuser 登录 → 200，租户列表 1 个
- 浏览器登录 testadmin → 200 并跳转 `/`；`/api/me` 返回 user=testadmin、
  active=test-tenant，CSRF Cookie 正常

### 1.10 Test Tenant 工作空间（通过，2026-11-19）
在 `test-tenant` 下为 `testadmin` 分配工作空间
`37c8fce0-5388-4d5d-bb69-62521ff5dee3`（模板 `base-v23`），启动后
`observed_state=running`，runtime 容器与 `rt-<uuid>-g0` 别名均在。
浏览器用 `testadmin` 登录 → 首页显示 Test Tenant / base-v23 / running / 「进入」→
进入空间 Host → 选择工作区目录 `/workspace` → 模型 `deepseek-flash` 可用，
`/_platform/files` 返回 200；发送「请只回复 OK」得到真实回复 **OK**（9.6K tok，1 秒）。
复跑：`powershell -File .\scripts\_tenant_ws.ps1`。

### 1.11 `stream interrupted` 失败定位与修复（2026-11-19）
用户在 Test Tenant 空间问「当前系统是什么？」得到 `PI_AI_ERROR / stream interrupted`。
定位：对应 `model_requests` 记录 latency≈20088ms、`usage_source=unknown`，正好是模型代理
`httpx.ConnectTimeout(connect=20s)`——容器到 `api.deepseek.com` 的一次瞬时连接超时，
不是密钥或沙箱问题（同一代理的普通调用 200，直接流式请求首字节 0.05s）。
修复：`connect` 超时 20s→30s、读空闲 60s→120s；上游流式调用最多 3 次带退避重试；
`model_requests` 插入改 `ON CONFLICT DO NOTHING` 保证重试幂等；异常打印 traceback 便于诊断。
复跑同一问题：Agent 6 秒内成功回答（Debian 12 / WSL2 内核 / Node 24 / `/workspace` /
DSH Web GUI），20.1K tok，缓存命中 96%。离线 22 项仍全绿。

### 1.12 产品化第一批：连接注册表与撤权（通过，2026-11-19）
新增 `services/api/app/connections.py`：进程内连接注册表，WS 与 `/plugins/events` SSE
均登记 `workspace_id / auth_session_id / user_id / epoch / generation`；
- 每 2 秒重查 DB（会话撤销、过期、用户禁用、空间停用、epoch/generation 变化），
  DB 不可用则关闭无法续验的连接
- 停用/停止空间、登出、切租户、成员停用、租户停用立即广播关闭
- 离线测试 `tests/test_connections.py` 5 项通过（广播、撤销、停用、DB 故障、按用户/会话关闭）

### 1.13 产品化第二批：生命周期一致性（通过）
- 新增部分唯一索引：`uq_op_active_ws`（每空间仅一个 queued/running 操作）、
  `uq_credential_active`（每空间每代仅一个有效凭据）；迁移 0002/0003/0004 已应用
  （当前版本 `0004_credential_hash_reissue`）
- 工作空间模型令牌改为由高熵种子 HMAC(wid:generation) 确定性派生，worker 重启不会与
  容器内已注入令牌不一致；撤销后可重新签发（去掉 token_hash 全局唯一索引）
- 令牌到期前 10 分钟自动 rebuild 轮换（保留卷）
- 修复 rebuild 三个真实缺陷：网络被 relay/llm 占用无法删除、卷带 generation 标签导致
  LABEL_CONFLICT、失败遗留的旧代容器未清理；改为按标签清理整个空间的容器与网络
- 实测：Test Tenant 空间 rebuild 成功（generation 2，单容器 running），容器内令牌与
  数据库有效凭据哈希一致；两个空间均恢复为有效令牌；会话历史在重建后仍可恢复
- 离线 32 passed / 6 skipped

### 1.14 产品化第三批：契约样本与升级门禁（部分通过）
- 真实抓取并脱敏的样本：`contracts/upstream/{web-http,events-sse,web-ws,session-contract}.sanitized.json`
  （来源：运行中的 dsh-v0.2.2-rc.4，`scripts/capture_contracts.py` 与
  `scripts/capture_session_contract.py`）
- `tests/test_upstream_contracts.py` 4 项通过：样本存在/脱敏、303 交换与根 HTML、
  text WS 形状、会话投影行（modelSelection/permissions/tokenUsage 等）
- Dockerfile 改 `ARG DSH_VERSION`，`build.ps1` 从 `.env.local` 传入；
  `templates` 增 `dsh_version` 列（迁移 0003）；`scripts/upgrade-check.ps1` 构建候选镜像、
  校验镜像内版本、跑契约+离线门禁并记录 `docs/upgrades.md`
- **待验证**：`upgrade-check.ps1` 的完整构建步骤当前被环境阻断——build 内 apt 拉取
  `deb.debian.org` 的 Packages 索引连接失败（同镜像 `docker run` 内 apt 正常，属构建网络波动）；
  已有镜像与运行服务不受影响。候选镜像换版本后的完整门禁需在 Docker 网络恢复后复跑。

### 1.15 管理后台交互梳理与重建（2026-11-19）
用户反馈 `/admin` 点击无提示、密码不可查看、不清楚租户与用户关系。定位与处理：
- 直接原因：`.env.local` 曾切到 `.localhost`，`nip.io` Origin 不再受信任 → `/api/admin/tenants`
  等请求 401，`onMounted(load)` 抛错后被吞掉，页面停在 `No Data`。已恢复 nip.io 配置，
  并在开发环境同时接受 `127.0.0.1` / `localhost` Origin（见 1.x 前的修复）
- **关系模型**：User 是全局身份（密码全局唯一，Argon2id 单向哈希）；Membership 把 User
  与 Tenant 关联并带 role(tenant_admin/member)/status；Workspace 归属 `(tenant_id, owner_id)`，
  owner 必须是该租户的有效成员。一个用户可属于多个租户，登录后选当前租户
- **密码**：不可查看是设计（单向哈希），页面顶部已明确说明；新建用户留空自动生成
  16 位强密码，创建后在“一次性密码”弹窗显示/复制；另有“重置密码”生成新密码同样只显示一次
- 新增后端：`GET /api/admin/users`、`POST /api/admin/users/{uid}/password`、
  `GET /api/admin/tenants/{tid}/members`、`GET /api/admin/tenants/{tid}/workspaces`
- 重建 `Admin.vue`：租户表（选择联动）、用户表、成员/空间/用量审计三页签、新建租户带配额、
  新建用户带显示/隐藏与自动生成、成员添加/停用、空间分配、所有操作 ElMessage 成功/错误提示
- 修复 `harness_app` 缺 `model_requests`/`budget_buckets` SELECT 权限导致用量页 500
- 浏览器实测：租户/用户列表加载、选租户后成员与空间加载、用量（34 请求/518252 输入 token）
  与审计事件正常；创建用户返回 201 并弹出一次性密码；修复了创建用户弹窗未关闭的小问题
- 离线 32 passed / 6 skipped

### 1.16 “进入”无响应与门户 UI 产品化（2026-11-19）
- **“进入”点不动根因**：平台管理员没有 active_tenant，旧逻辑 `ws.tenant_id != identity.tenant_id`
  使票据接口返回 404，前端未捕获异常；同时管理权限本不应授予读取成员文件/终端。
  正确修复：`GET /api/workspaces` 对平台管理员只返回其**本人名下**空间（管理视图在 /admin），
  票据仍严格校验租户归属。已为 admin 在 test-tenant 分配并启动本人空间
  `00a36e23-182b-4fce-a9cb-86829a3673b2`，重新登录后 active_tenant 正确、票据 201、
  “我的空间”只显示本人 1 个空间。
- **UI 产品化重做**：App.vue 增加品牌栏、导航、用户下拉（切换租户/退出）；Home.vue 改为
  页头 + 统计卡 + 空间卡片网格 + 状态标签 + 加载/空状态 + 票据进度弹窗；Login.vue 改为
  品牌化登录卡；所有动作接 ElMessage 成功/错误提示，不再静默失败
- 依赖新增 `@element-plus/icons-vue`；离线 32 passed / 6 skipped

### 1.17 浏览器集成测试套件（2026-11-19）
用浏览器驱动真实页面（非 Mock）逐项验证：
| Case | 操作 | 结果 |
|---|---|---|
| 1 | 错误密码登录 | ✅ 页面显示 `Invalid credentials` |
| 2 | 正确密码登录（admin） | ✅ 跳转工作台，仅显示本人 1 个空间、统计卡正确 |
| 3 | 点击“进入工作空间” | ✅ 票据 201 → 303 → dsh Web 打开，零控制台错误 |
| 4 | 工作区选择 `/workspace` 后发消息 | ✅ 真实 DeepSeek 回复 `OK`，3 秒，9.6K tok |
| 5 | 管理页 API | ✅ tenants 200(2)、users 200(6)、templates 200(23)、workspaces 200(1=本人) |
| 6 | a1 越权访问 admin 空间 | ✅ 自己只见 1 个空间；他人空间 GET 404、票据 404 |
| 7 | 登出后会话 | ✅ logout 200；随后 `/api/me` 401 |

发现的小问题：新空间首次进入需要手动选目录（dsh 未提供稳定预选接口），手册 8 节允许记录该方式；
后续可写 profile patch 预置 `/workspace`。离线 32 passed / 6 skipped。

### 1.18 toB 能力补齐（2026-11-19）
- 新增平台审计 `GET /api/admin/audit`（按租户/动作过滤）、用户生命周期
  `PATCH /api/admin/users/{uid}`（停用级联撤销会话与成员）、会话列举/吊销
  `GET /api/admin/users/{uid}/sessions`、`DELETE /api/admin/sessions/{sid}`；
  实测 audit 200(100 条)、users 200(6)、某用户 sessions 200(7)
- 实现 `scripts/backup.ps1`：pg_dump 自定义格式（仅 harness schema）+ 6 个卷 tar +
  SHA256 + manifest，实测 `BACKUP_OK`（dump 78KB、6 卷、manifest）
- 实现 `scripts/restore.ps1 -Target test -Manifest <file>`：仅恢复到隔离数据库
  `harness_restore_test`，校验 checksum、清会话/票据/租约、epoch+1、从 stopped 恢复；
  实测 `RESTORE_OK`（6 卷恢复、文件可见）。修复了 pg_restore17/PG12 的
  `transaction_timeout` 不兼容、PowerShell 二进制重定向损坏 tar、级联删除顺序等问题
- 新增 `tests/test_admin_ops.py` 3 项；离线总计 **35 passed / 6 skipped**
- 完整 toB 差距与路线见 `docs/TOB_READINESS.md`；对外仍需 SSO/MFA、密钥托管、HTTPS、
  渗透测试、多副本、升级门禁网络复验等 P0 项

### 1.19 企业 SSO 与 MFA（实现完成，真实 IdP 待现场验证）
- OIDC：新增 `services/api/app/auth_oidc.py`（discovery、authorize URL、PKCE S256、
  token 交换、id_token JWS/JWKS 校验、nonce 校验、签名 state），端点
  `GET /api/auth/oidc/config|/start|/callback`；支持 JIT 开通（`OIDC_AUTO_PROVISION`）。
  配置项 OIDC_ISSUER/CLIENT_ID/CLIENT_SECRET/REDIRECT_URI 在 `.env.example`；
  登录页在配置后显示“使用企业账号登录”
- MFA：users 增加 `mfa_secret`/`mfa_enabled`（迁移 0005）；端点 enroll/verify/disable/complete；
  已启用 MFA 的用户，密码正确后只返回 `mfa_required` 与短期票据，输入 TOTP 才建立会话；
  登录页自动显示验证码输入
- 离线测试 `tests/test_sso_mfa.py` 3 项通过（OIDC 默认关闭、TOTP 注册→验证→登录→完成、
  错误码拒绝）；总计 **38 passed / 6 skipped**
- 修复：网关 catch-all 路由先于新路由注册导致 404、JSONResponse 丢弃注入 Response 的 Cookie
- 真实栈复验（API 镜像重建后）：`GET /api/auth/oidc/config` → 200 `{"enabled":false}`；
  登录 200；`POST /api/auth/mfa/enroll` → 200（secret 返回）。离线与真实栈一致
- **待验证**：真实企业 IdP 的 discovery/JWKS/JIT 全流程（当前无 IdP 配置），
  以及生产 MFA 强制策略；`docs/TOB_READINESS.md` 中对应 P0 项仍需现场验收

### 1.20 生产 HTTPS + Docker secrets（实现与静态验证通过）
- `common/harness_common/config.py` 的 `_env()` 支持 `<NAME>_FILE`：优先从挂载的 secret
  文件读取（compose/K8s secret），不再把口令放进进程环境；实测
  `DEEPSEEK_API_KEY_FILE=secrets/deepseek_api_key.txt` → 读取长度 35、前缀 `sk-`
- 新增 `scripts/init-secrets.ps1`：从 .env.local 生成 `secrets/*.txt`（gitignored，空值也建文件避免挂载失败）
- 新增 `compose.prod.yaml`：HTTPS edge（8080→8443 跳转、TLS1.2/1.3、HSTS、安全头、
  WebSocket）、Docker secrets 注入、每服务内存/CPU 限制、json-file 日志轮转；
  `docker compose -f compose.prod.yaml config --quiet` 通过
- 新增 `infra/nginx/nginx-prod.conf`；用注入 hosts 的方式 `nginx -t` 通过（`syntax is ok`）
- 新增 `scripts/gen-devcert.ps1`：用 alpine/openssl 生成**自签名**开发证书
  （`infra/nginx/certs/`，gitignored）；生产必须替换为受信任 CA/Let's Encrypt 证书
- **待验证**：用真实域名证书启动 `harness-prod` 项目做 TLS 握手、Secure Cookie、
  HSTS 与 WebSocket over TLS 的端到端验证（当前端口 8080 被开发栈占用，且无真实证书）

### 1.21 多副本撤权（Redis 跨进程广播，实现与离线验证通过）
- `ConnectionRegistry` 增加 Redis pub/sub：本地关闭后向 `harness:revocations` 广播
  `{sender, kind, ids}`，其它 API 副本收到后关闭本进程的匹配连接；
  忽略自身消息，Redis 不可用时退化为 2 秒 DB 重查（安全网）
- 参数化 `redis_url`（`REDIS_URL`）；`compose.prod.yaml` 增加 redis 服务与 api 的 `REDIS_URL`
- `tests/test_multireplica.py` 2 项通过：本地关闭并广播、第二副本收到消息后关闭连接
- 全量离线 **40 passed / 6 skipped**；`compose.prod.yaml config --quiet` 通过
- 真实栈复验：API 镜像重建（含 redis/pyotp/PyJWT 依赖）后 health 200、OIDC config 200
- **待验证**：真实两个 API 副本 + Redis 的端到端（停用空间后 3 秒内两副本的 WS 均关闭）；
  首次构建因 pypi 读超时失败，重试成功（依赖均已安装）

### 1.22 PostgreSQL PITR 演练（通过）
- 新增 `compose.pg.yaml`：独立 PG16 实例（15432），`wal_level=replica`、`archive_mode=on`、
  WAL 归档到 `pg_archive` 卷；**不触碰本机 5432 的现有 GIS 数据库**
- 新增 `scripts/pg-pitr-drill.ps1`：建基线数据 → pg_basebackup → 写入后续数据 →
  用 `recovery_target_time` 恢复到基础备份时间点 → 校验行数
- 实测：`archive_mode=on`；基线行 `before-backup`、后续行 `after-backup`；
  恢复结果 `restored_rows=before-backup`（后续行被正确排除）→ **PITR_DRILL_PASS**
- 修复：Docker 地址池耗尽（复用现有 compose 网络）、归档卷 UID 权限（chown 999）、
  PowerShell 把 psql NOTICE 当终止错误
- 演练资源已清理（容器/卷/临时目录），主栈 health 200；离线 40 passed / 6 skipped
- 说明：这是独立 PG 实例的 PITR 能力验证；现有 Windows PG 实例启用归档需系统级配置变更，
  按手册要求需维护者确认后实施

### 1.23 运行时隔离渗透验证（T06，发现并修复重大漏洞）
- 新增 `scripts/runtime_isolation_probe.py`（在容器内运行）：断言 UID=10001、CapEff 为空、
  rootfs 只读、无 Docker socket、无法访问宿主 PG、无法访问外网、只能访问 model-proxy、
  无法访问其它空间别名
- **首次实测发现严重漏洞**：runtime 容器被创建在默认 `bridge` 上（有宿主与外网通路），
  再接入空间专网 → `no_host_pg=false`、`no_external_net=false`
- 修复 `DockerRuntimeDriver.start/_container_config`：容器**只 birth 在空间 internal 网络**，
  通过 NetworkingConfig + 显式重连确保 `rt-<uuid>-g<gen>` 别名生效；不再出现 `bridge`
- 复测三个空间全部 `ISOLATION_PASS`（含 `no_host_pg`、`no_external_net`、`model_proxy_allowed`）
- `tests/integration/test_docker.py` 增加：单一网络断言 + 容器内探针断言；
  `HARNESS_INTEGRATION=1` 下 2 项通过
- 同时修复从零迁移的幂等性（0002 索引 IF NOT EXISTS、0003/0005 列存在检查）并 bootstrap
  `harness_test` schema 跑通全部迁移到 0005；PG 集成 3 项通过
- 全量（含集成）**45 passed / 2 skipped**；默认离线 42 passed / 6 skipped

### 1.24 容量基线采集（T17 部分）
- 新增 `scripts/capacity-baseline.ps1`，生成 `docs/capacity.md`：宿主机（16 vCPU / 31.29 GB /
  C: 59.93 GB 可用）、Docker disk usage、每容器 CPU/内存快照、
  `harness.model_requests` 的按模型平均/最大延迟与 token 总量
- 实测采集成功；runtime 容器约 0.3% CPU、~309 MiB / 1 GiB
- **待验证**：T17 完整压测（冷/热启动各 5 次、1/2/4 空间并发固定任务、失败率、磁盘增长曲线）
  需在专用测试环境执行，当前只提供可复跑采集与真实快照

### 1.25 MFA 自助 UI 与细粒度 RBAC
- App.vue 用户下拉新增“安全设置（MFA）”：一键 enroll（显示一次性密钥、复制）、输入验证码确认启用、关闭 MFA
- 新增 `services/api/app/permissions.py`：11 项细粒度权限（tenant/user/member/workspace/usage/audit/template 的读写），
  角色映射：平台管理员全部、租户管理员 8 项、成员仅 workspace:read；
  已对租户/用户/成员/空间/模板/用量/审计端点加 `require_permission` 依赖
- `tests/test_rbac.py` 3 项通过：租户管理员有成员权限、普通成员无审计/用量/用户读权限、平台管理员全通过
- 全量离线 **43 passed / 7 skipped**
- 真实栈复验：health 200；平台管理员 `/api/admin/audit` → 200；普通成员 a1 同一端点 → **403**（RBAC 生效）

### 1.26 SCIM 2.0 用户开通
- 新增 `services/api/app/routers/scim.py`：SCIM 2.0 User 资源（list/filter/get/create/patch/delete），
  Bearer token 从 `SCIM_BEARER_TOKEN`（或 `_FILE` secret）读取，未配置时 503 禁用
- 停用/删除 SCIM 用户会级联撤销会话并写审计；`/scim/` 写入不受浏览器 Origin 校验（服务端到服务端）
- `tests/test_scim.py` 2 项通过：token 鉴权、用户创建→激活→停用→filter→删除生命周期
- `.env.example`、init-secrets、compose.prod.yaml 已加入 SCIM secret；prod config 校验通过
- 全量离线 **45 passed / 7 skipped**

### 1.27 服务账号（Scoped API Tokens）
- 新增 `ApiToken` 模型 + 迁移 0006（harness 与 harness_test 均已升级到 0006）
- 端点 `POST/GET/DELETE /api/me/tokens`：创建时仅一次返回明文 token，列举不含 hash，撤销即时生效
- 权限 scope 白名单 12 项；SCIM 现同时接受静态 bearer 与 `scim:write` scope 的 API token（记录 last_used_at）
- `tests/test_tokens.py` 3 项通过：创建/列举/撤销、未知 scope 拒绝、SCIM 接受作用域 token
- 全量离线 **48 passed / 7 skipped**

### 1.28 全流程验收复跑（真实 Docker / PostgreSQL / 浏览器 / DeepSeek）
- **自动化套件（带集成环境）**：`53 passed / 2 skipped`；三空间隔离探针全部 `ISOLATION_PASS`
- **真实栈健康**：health live 200、ready ok；迁移版本 `0006_api_tokens`；6 用户 / 2 租户 / 3 空间
- **浏览器 E2E（真实 Chrome，经 in-app browser）**：
  1. 登录：错误密码显示 `Invalid credentials`；正确管理员登录进入工作台
  2. 管理页：租户/用户列表加载；点选租户显示成员（角色/状态）与「成员 / 工作空间 / 用量与审计」页签；审计日志显示真实事件链
  3. **发现并修复真实故障**：进入工作空间根路径返回 `Internal Server Error`。根因：隔离网络无外部 DNS，运行时适配器按公网 authority 访问 dsh 时 `[Errno -3] Temporary failure in name resolution`。
     修复 `services/worker/worker/driver.py`：为运行时容器增加 `extra_hosts=[<workspace_host>:127.0.0.1]`。重建 worker 后由 reconcile 自动重建运行时（新容器 01:04:12Z 创建，`docker inspect` 确认 ExtraHosts 已注入、仅挂内部专网），工作空间正常打开。
  4. **真实 DeepSeek 对话**：发送指令 → `已完成，用时 2秒` / `OK` / `9.6K tok·缓存命中 91%`（真实模型响应，非 mock）
  5. 文件：`PUT→GET→LIST→DELETE` 全链路通过（上传 200、下载内容一致、列表可见、删除 204）
  6. 终端：WebSocket PTY `echo TERMOK999` → 回显 `TERMOK999`，确认交互终端可用
  7. RBAC：普通成员 a1 访问 `/api/admin/audit` → **403**；管理员 → 200
  8. **发现并修复 UI 缺陷**：原 `isTenantAdmin = !!tenants.length` 导致任何成员都看到「管理」菜单。
     `/api/me` 的 `TenantBrief` 增加 `role` 字段，`isTenantAdmin` 改为按当前租户角色判断。复验：a1 在 tenant-a(member) 仅见「工作台」；切换至 test-tenant(tenant_admin) 后出现「管理」。
  9. 租户切换：弹窗选择 Test Tenant → `active_tenant_id` 切换、菜单随角色刷新；退出登录 → 跳回 `/login` 并提示「已退出」
- 新增回归测试：`test_runtime_config_pins_public_host_to_loopback`（ExtraHosts 与内部网络）、`test_me_role.py` 2 项（role 字段）
- 修复后全量复跑（离线）**51 passed / 7 skipped**，（带集成环境）**56 passed / 2 skipped**；前端与 API 镜像已重建并上线（本轮最终计数见 1.31）

### 1.29 极端条件 / 异常输入验收（本轮）
- **离线异常测试** `tests/test_edge_cases.py`：**26 passed / 4 skipped**（4 项为 Linux dir_fd 文件服务，改由容器内真实探针覆盖）
  - 认证滥用：空/超长字段、畸形 JSON、失败 5 次限流 429、无效/过期/撤销 Cookie、禁用用户、错误 CSRF、跨租户切租户被拒、成员资格撤销后 403
  - 畸形输入：非法 UUID 422、未知 action 404、重复租户/用户 409、MFA 未 enroll/错误码、SCIM 怪异用户名归一化+重复冲突、token 空 scope/越界有效期
  - 隔离：跨租户空间统一 404、跨租户成员列表 403、跨租户票据 404
  - 幂等：相同 key 同参数返回同一操作、不同参数 409、缺 key 409
  - 文件服务路径语法：穿越/绝对/反斜杠/NUL/空目录全部拒绝
- **容器内真实文件服务探针** `scripts/fileservice_probe.py`：**19/19 PASS**（`FILESERVICE_PROBE_PASS`）
  - 路径穿越/符号链接/非普通文件/ETag 冲突/创建冲突/超限写入全部拒绝；读写建移动删正常
- **真实网关异常**：票据创建 201；错误 Origin → 403；合法兑换 → 303；重放 → 403；错误 Host 绑定 → 403
- **跨空间网络隔离**：从空间 A 解析空间 B 别名 DNS 失败；直连 B 容器 IP → 101(Network unreachable)
- 本轮新增 5 份文档：`docs/REQUIREMENTS.md`、`DESIGN.md`、`TECHNICAL.md`、`DEPLOYMENT.md`、`OPERATIONS.md`

### 1.30 修复：未登录点击「工作台」报「无权限」
- 现象：登录页点击顶部「工作台」（或直接访问 `/`、其他受保护路由）会渲染受保护视图并调用需要会话的 API，前端抛出 `无权限 / Not authenticated`。
- 根因：`router.ts` 虽有 `meta: { auth: true }`，但**缺少导航守卫**执行该元数据；顶部菜单与品牌 Logo 也未区分登录态。
- 修复：
  - 新增 `apps/portal/src/auth.ts`：共享响应式 `me` / `ensureMe()`，先解析 `/api/me` 再放行路由。
  - 新增 `apps/portal/src/authGuard.ts`：`beforeEach` 守卫，未登录访问受保护路由 → 重定向 `/login`；已登录访问 `/login` → 重定向 `/`；文件/终端路由也纳入保护。
  - `App.vue`：未登录时隐藏「工作台」菜单，品牌点击改为跳转 `/login`；复用共享登录态。
  - `Login.vue`：登录/MFA 成功后先 `loadMe()` 再跳转，确保守卫看到最新会话。
- 回归：`apps/portal/src/authGuard.test.ts` 4 项通过（未登录重定向、已登录放行、登录页双向重定向）
- 真实浏览器复验：未登录访问 `/` 与 `/admin` 均自动跳 `/login`，无「无权限」错误；登录成功后「工作台/管理」正常出现；登出干净返回登录页

### 1.31 最终全量计数（含极端条件与前端）
- 离线后端 **77 passed / 11 skipped**；带集成环境 **82 passed / 6 skipped**；前端 vitest **4 passed**
- 容器探针：隔离 3/3 PASS、文件服务 19/19 PASS；真实网关异常与跨空间网络隔离全部通过
- 密钥扫描 CLEAN；health 200

### 1.32 租户容器资源配额（CPU / 内存 / PIDS）
- 产品方案见 `docs/TENANT_RESOURCES.md`（GPU 不在本轮范围：宿主无 NVIDIA Container Toolkit）
- 迁移 `0007_tenant_resources` 已应用于 harness / harness_test（版本 `0007_tenant_resources`）
- 模型：`tenants` 新增单空间规格 3 项 + 运行态总量上限 3 项；`workspaces` 新增可空资源字段（NULL=继承模板）
- 平台上限常量 `limits.py`：CPU 1–32/总量 256、内存 256MiB–64GiB/总量 512GiB、PIDS 64–4096/总量 65536
- 校验：租户声明不超平台上限、单空间≤总量、下调总量不得低于当前用量；分配可覆盖但不超租户规格；start 时校验运行态总量
- worker `_spec_for` 优先使用空间资源，老空间 NULL 回退模板
- `tests/test_tenant_resources.py` 5 项通过；全量离线 **82 passed / 11 skipped**；前端 4 项通过并已重建
- 真实栈验证：
  - PATCH test-tenant → cpu_per_space=2/mem=2GiB/pids=512，总量 12核/12GiB/3072 → 200
  - 分配 testuser 空间（显式 cpu=2/mem=2GiB/pids=512）→ 201；start → 202
  - `docker inspect` 新运行时：`nano_cpus=2000000000`、`mem=2147483648`、`pids=512`（与声明一致）
  - 浏览器 UI：新建租户表单含 6 项资源字段；实建 `ui-res-927567` = 3核/2GiB/512pids、总量 6核/4GiB/1024；工作台卡片显示「资源 2核/2.0GB/512pids」
- 运维发现并处理：历史遗留 21 个孤立空间网络占满 Docker 地址池（`all predefined address pools have been fully subnetted`），清理后新空间正常启动；新增 `scripts/cleanup-space-networks.ps1`（默认 dry-run，`-Apply` 执行）

### 1.33 修复：工作台「启动/停止」按钮报 `crypto.randomUUID is not a function`
- 现象：工作台个人空间点「启动」「停止」弹出 `crypto.randomUUID is not a function`；管理页「分配空间」同样风险
- 根因：`crypto.randomUUID()` 仅在安全上下文（HTTPS/localhost）可用；开发门户经 `http://portal.127.0.0.1.nip.io:8080` 访问，不是安全上下文
- 修复：`apps/portal/src/api.ts` 新增 `newId()`——优先 `crypto.randomUUID()`，不可用时用 `crypto.getRandomValues()`（非安全上下文可用）生成 UUID v4，兜底 `Math.random()`；`Home.vue`、`Admin.vue` 的 `Idempotency-Key` 全部改用 `newId()`
- 回归：`apps/portal/src/api.test.ts` 2 项（randomUUID 路径 + 非安全上下文回退路径）；前端共 **6 passed**
- 真实浏览器复验：点「停止」→ `已提交停止请求`、期望状态转 stopped；点「启动」→ `已提交启动请求`、期望状态转 running；无 `crypto` 错误。worker 日志显示 stop/start 均 succeeded，运行时容器被重建

### 1.34 P0 加固（正确性 / 一致性）
1. **对账绕过配额**：新增 `common/harness_common/quotas.py:check_start_quotas()`，API 与 worker 共用；worker `process(OP_START)` 现在也会拒绝超出 `max_running` 或资源总量的 start（失败置 `OP_FAILED`，不创建容器）
2. **登录限流多副本失效**：新增 `services/api/app/ratelimit.py:LoginRateLimiter`，Redis sorted-set 跨副本共享计数（失败自动降级本地）；`app.state.login_limiter` 注入，`auth.login` 改用之
3. **DB idle-in-transaction 锁泄漏**：`make_engine` 对 PG 连接设置 `statement_timeout=120s`、`idle_in_transaction_session_timeout=60s`；`get_db` / `session_scope` 异常路径显式 rollback。真实验证应用连接 SHOW 分别为 `2min` / `1min`
4. **generation 漂移与孤儿网络**：API rebuild 不再提前 bump generation（由 worker 成功后推进）；worker 每 5 分钟调用 `driver.gc_networks(keep)`，只保留当前代网络、先摘除 relay/llm 再删除
5. **附带修复**：快速 stop→start 触发 `uq_op_active_ws` 唯一约束导致 500 → 捕获 `IntegrityError` 返回干净 409
- `tests/test_p0_hardening.py` 6 项通过；全量 **88 passed / 11 skipped**（离线）、**93 passed / 6 skipped**（集成）
- 真实栈：镜像重建上线、health 200；worker 日志出现 `gc removed 1 orphan space networks`，4 个当前空间网络与 4 个运行时均完好；API 日志无新增 500

## 5. 交付与复跑入口

启动顺序（第 10 节）：
```
Copy-Item .env.example .env.local
.\scripts\init-local.ps1
# 维护者交互输入 postgres 口令后执行一次：
psql -h 127.0.0.1 -U postgres -d postgis -W -f .\db\bootstrap.psql
.\scripts\doctor.ps1
.\scripts\build.ps1
.\scripts\migrate.ps1
.\scripts\admin-create.ps1
.\scripts\up.ps1
.\scripts\test.ps1 -Suite offline
```
浏览器：`http://portal.localhost:8080`。
首个管理员：`admin-create.ps1` 交互创建（当前本地库已创建 `admin`）。
本地域名：若 `*.localhost` 不解析，需在 hosts 写入 `127.0.0.1 portal.localhost` 与各
`w-<uuid>.localhost`，并让代理软件对这些名称直连；hosts 不支持通配。
