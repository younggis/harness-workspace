# 多租户 Web Harness 开发与验收手册

**目标环境**　Windows 11 · Docker Desktop（Linux 容器）· FastAPI · Vue 3 · 本机 PostgreSQL · DeepSeek  
**交付对象**　负责实现、代码审查和测试的 Codex，以及负责本地验收的项目维护者  
**方案版本**　1.0，2026-11-18。本文是实施规格。文中的项目脚本、镜像、平台接口和页面均为待开发交付物。上游已提供的能力在第 2 节单独列出。

## 1. 做完之后，用户能做什么

管理员创建租户 A，添加成员小王，分配一个 Linux 工作空间，选择镜像和资源规格。小王登录后点击“进入工作空间”，能上传文件、让 Agent 分析、展开工具调用、批准待确认步骤、查看修改、打开交互式终端，并下载产物。关闭浏览器后，已经开始的任务可以继续；再次登录能看到已提交的会话和项目文件。管理员停用空间后，已打开的页面、终端和模型调用也失去权限。成员属于多个租户时，必须先选当前租户。

**首版决策。** 面向单台开发机和受信任组织成员。租户是身份和配额边界，工作空间是执行和存储边界；一个租户有多个成员，一个成员关系默认分配一个个人空间。每个运行中的空间拥有自己的 Linux 容器、网络、项目卷和会话卷。首版在本机完成闭环；Kubernetes 属于通过本地验收后的部署适配。

| 范围 | 首版交付标准 |
|---|---|
| 平台管理 | 平台管理员管理租户；租户管理员管理本租户成员、分配空间、设置规格、启停与停用空间、查看状态和用量 |
| 用户工作台 | 登录、租户切换、个人空间、原生 Harness 对话、过程时间线、操作批准/拒绝、取消任务、历史恢复 |
| 文件与操作系统 | 文件树、创建目录、上传下载、文本编辑、重命名、删除、差异查看；容器内非 root Linux 终端支持交互和 Ctrl+C |
| 首版运维 | 幂等分配、资源上限、断线恢复、失败诊断、备份恢复、日志脱敏、测试环境独立 |
| 下一阶段 | 多节点调度、共享项目、互联网租户的强沙箱、任意网络出口策略、硬磁盘配额、镜像自助构建。以上能力不计入本地首版完成度 |

**示范验收任务。** 给 A/小王上传含三个点的 UTF-8 文件 `points.geojson`，让 Agent 用 Python 标准库统计要素数和包围盒，写入 `result.json`。前端展示实际工具操作；终端读取到同一文件；停止后重建，文件和历史仍在；A 的另一成员及租户 B 均不能访问。全过程无需 GIS 数据库扩展。

## 2. 上游复用与版本基线

| 组件 | 实现决策 |
|---|---|
| Agent 与对话 | 复用 deepseek-harness 的 Web profile、Agent 循环、会话日志、工具、模型适配和审批。原生 Web 作为工作台中的“Agent”入口，以工作空间独立域名顶层打开。 |
| Vue 3 | 自建登录、管理后台、空间首页、文件和终端。入口显示“Agent / 文件 / 终端”；首版允许 Agent 在独立页面打开。 |
| 过程展示 | 先试原生界面的计划、消息、工具和重连表现。对缺失项补一个固定版本的 Web 客户端/事件插件，从实际事件渲染。禁止把终端文本猜测成模型分析或伪造执行状态。 |
| 多租户 | 由平台实施。每个空间独立运行 dsh，独享 `DSH_HOME`；平台从认证身份映射空间，平台 API 不在自身进程内启动用户 Shell。 |
| 通用能力 | 镜像模板决定可用命令，profile 决定工具和插件，模型配置决定允许的路由。首版实现一个基础模板、一个 DeepSeek 路由；新增模型或 GDAL 模板沿既有接口扩展。 |

上游默认 `dsh web` 监听回环地址，支持反向代理和自定义模型端点。持久会话事件与进程内瞬时流有不同生命周期。SDK 最小配置中的工作目录也不能用作系统隔离边界。参见文末 [1]–[5]。

**M0 必须提交版本清单** `upstream.lock.json`：源码 URL、完整 commit SHA、对应 npm 版本或源码构建方式、Node 与包管理器版本、基础镜像 digest、镜像内 UID、Web 端口、启动参数、认证交换路径、模型配置来源、代理端到端测试结果。固定一个已验证组合并提交锁文件和 MIT/第三方通知。不要猜测 commit、未公开 RPC 名称或配置字段，也不要在运行时执行未锁版本的 npx 安装。升级通过同一套契约测试后单独合并。

## 3. 本机部署拓扑

浏览器只访问一个发布到 Windows 回环地址的端口。控制服务采用 Compose，沿用 Windows 上已有的 postgis 数据库。这样可以复现同一套依赖，也便于 Codex 在干净环境重复测试。

| 服务 | 职责 | 连接与权限 |
|---|---|---|
| edge | Nginx 托管 Vue 构建产物，按 Host 分发门户和工作空间，透传 WebSocket | 唯一端口映射 `127.0.0.1:8080:8080`；门户 `portal.localhost:8080`，空间 `w-<uuid>.localhost:8080`。只连前端网络 |
| api | FastAPI。平台接口、身份、CSRF、审批归属、工作空间网关、审计和用量查询 | 连前端网络、服务网络和能访问本机 PG 的网络；无 Docker socket。首版网关单进程，长连接登记于进程内 |
| worker | 从 PostgreSQL 领取操作、创建容器/卷/网络、绑定 relay 和模型服务、探活、对账 | 唯一持 Docker Engine socket 的固定镜像；仅数据库任务输入，无公网或网页入口 |
| relay | 固定目标的 HTTP/WebSocket 转发器，转发 API 已授权的工作空间请求 | 服务网络 + 每个活跃空间的专用网络；无 DB 密钥、模型密钥和 Docker socket；仅接受 API 签名的请求 |
| llm | OpenAI 兼容的模型代理。验证空间令牌、并发与预算，把流式响应传回 dsh | 各空间专网 + 可出网网络；固定上游 DeepSeek。真实供应商密钥仅注入该服务；数据库账户仅获必需表权限 |
| runtime | 每空间一实例，运行 dsh、工作空间 HTTP 适配器、文件操作和 PTY | 只接自己的 internal bridge；无主机端口、Docker socket、宿主路径及平台密钥；项目和会话写入独立 named volumes |
| PostgreSQL | 现有 Windows 实例，保存平台元数据 | 主机端 `127.0.0.1:5432/postgis`；容器服务用 `host.docker.internal:5432/postgis`。仅使用专用 schema 和角色 |

**网络落点。** Compose 静态网络可命名为 front（edge/api）、control（api/relay，internal）和 backend（api/worker/llm 到 Windows PG，仅 llm 需要外部模型出口）。runtime 不接这些静态网络，动态创建时显式指定空间专网。relay 必须在其所有可达接口验证服务签名，包括 WebSocket；llm 对每次调用校验令牌。单独的 internal bridge 不能替代应用鉴权或主机防火墙。worker 的 Engine 权限足以控制 Docker 主机，只接受固定资源模板与类型化操作，不接受网页传入 Docker 参数、挂载路径或任意镜像。

**请求路径。** 浏览器 → edge → api 鉴权 → relay → 指定 runtime 的适配器 → 本空间 dsh、文件或 PTY。模型请求从 runtime → 本空间网络中的 llm → DeepSeek。worker 从数据库获取期望状态后才调用 Docker。脚本把工作空间网络、容器、卷打上安装 ID、环境、空间 ID、资源类型标签；网络别名如 `rt-<uuid>-g<generation>` 全局唯一。llm 在每个空间网络获得同一个服务别名 `model-proxy`。relay 和 llm 是接入多个网络的受信任服务；不允许它们提供通用 HTTP 代理、CONNECT、任意 DNS 目标或 IP 转发能力。

**本地命名。** M0 以浏览器实测门户名和测试空间名能解析到回环。不同 Windows DNS/代理环境下，若通配本地域名不可用，开发脚本列出需要映射到 127.0.0.1 的具体名称，由维护者选择本机 DNS 或精确 hosts 记录，hosts 不支持通配。代理软件须为这些名称直连。不要用不同端口区分平台 Cookie；Cookie 没有端口隔离。

## 4. 开发机初始化与配置

从 PowerShell 执行以下只读预检。确认 Docker 为 Linux 容器模式，数据库名匹配，记下实际版本和端口占用。psql 未加入 PATH 时，使用本机 PostgreSQL 安装目录下的 psql.exe。构建镜像和首次安装依赖需要网络或已准备的本地缓存。

```powershell
docker version
docker compose version
docker info --format '{{.OSType}} {{.Architecture}}'
Test-NetConnection 127.0.0.1 -Port 5432
psql -h 127.0.0.1 -p 5432 -U postgres -d postgis -W -c "select current_database(),current_user,version();"
Get-NetTCPConnection -LocalPort 8080 -ErrorAction SilentlyContinue
```

**数据库初始化。** 已提供的 postgres 超级用户仅供维护者通过交互提示输入密码做一次引导。Codex 交付 `db/bootstrap.psql`。下列 SQL 表示第一次引导的权限边界；脚本实际执行前检查每个对象的存在和归属，若与既有对象重名且归属不符则退出。不要修改已有 GIS 表、public 的权限、数据库默认 search_path 或安装 PostGIS。数据库超级用户口令不注入应用。

```sql
CREATE ROLE harness_owner LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;
CREATE ROLE harness_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;
CREATE ROLE harness_llm LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;
CREATE SCHEMA harness AUTHORIZATION harness_owner;
GRANT CONNECT ON DATABASE postgis TO harness_owner, harness_app, harness_llm;
GRANT USAGE ON SCHEMA harness TO harness_app, harness_llm;
ALTER ROLE harness_owner IN DATABASE postgis SET search_path = harness, pg_catalog;
ALTER ROLE harness_app IN DATABASE postgis SET search_path = harness, pg_catalog;
ALTER ROLE harness_llm IN DATABASE postgis SET search_path = harness, pg_catalog;
```

在 psql 中用 `\password harness_owner`、`\password harness_app`、`\password harness_llm` 分别设置密码。owner 仅用于迁移；Alembic 显式使用 `version_table_schema="harness"`，限定 autogenerate include_schemas/过滤器，仅匹配本项目 schema。迁移尾部对 app 授予各业务表所需 DML，对模型代理仅授予配额/授权视图的 SELECT 和用量/预留操作所需权限，使用 UUID 主键；若采用序列，补相应 USAGE。不要向 PUBLIC 添加权限。核查既有 PUBLIC 继承权限；若旧 postgis 库已向 PUBLIC 开放敏感业务表且无法局部隔离，则用同实例独立数据库部署，并记录变更。测试另建 `harness_test` schema、专属角色及迁移版本表，不能复用开发 schema 或运行全库清理。

**容器访问主机 PG。** 主机连通后，从与 api 相同网络的诊断容器，以 harness_app 实际登录，执行 `select current_database(), current_user, inet_client_addr()`。仅 TCP 成功不算通过。若失败，依次检查 DNS、端口、PostgreSQL 监听、数据库日志、pg_hba.conf 和 Windows 防火墙。用主机 psql 查询 `SHOW listen_addresses`、`SHOW hba_file`、`SHOW config_file`。确需变更时先备份，仅对实际接口及来源、postgis 库和应用角色放行 SCRAM；重载 HBA，监听地址的变更按本机维护窗口重启。禁止为跑测试直接开放 0.0.0.0/0、trust 或关闭防火墙。若现网策略禁止容器访问该实例，交付诊断并切到单独的开发 PG 实例；不可悄悄覆盖现有库。参见 [7]、[9]。

**配置清单。** 仓库只提交 `.env.example`；实际密码、平台签名密钥、模型密钥放入忽略版本控制的本机配置，Compose 按服务单独注入，禁止全服务共用一个含所有秘密的 env_file。含特殊字符的数据库密码使用 SQLAlchemy URL.create 从字段构造连接，不手拼 DSN。

```dotenv
APP_ENV=development
INSTALLATION_ID=harness-local-dev
PORTAL_ORIGIN=http://portal.localhost:8080
WORKSPACE_HOST_SUFFIX=.localhost:8080
PG_HOST=host.docker.internal
PG_PORT=5432
PG_DATABASE=postgis
PG_SCHEMA=harness
PG_APP_USER=harness_app
PG_APP_PASSWORD=
PG_MIGRATION_USER=harness_owner
PG_MIGRATION_PASSWORD=
PG_LLM_USER=harness_llm
PG_LLM_PASSWORD=
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-flash
DEEPSEEK_API_KEY=
REASONING_EFFORT=high
THINKING_ENABLED=true
RELAY_SIGNING_KEY=
SESSION_SIGNING_KEY=
```

`init-local.ps1` 生成随机的平台密钥，对缺失配置按服务报错，只打印缺失变量名。DeepSeek 使用维护者自行填入的有效密钥；已在对话中发送过的密钥建议先轮换。Vite 的 `VITE_*` 变量只放公开参数。记录诊断时遮蔽 DSN、Authorization、Cookie、一次性票据、dsh 启动 URL、模型输入和命令内容。

## 5. 数据模型、角色与授权

所有时间为 timestamptz，以 UTC 存储。主键用应用生成的 UUID；用户可见名称不参与容器、卷或目录拼接。tenant_id 与 workspace_id 同时出现时用复合外键保证归属。列表必须分页；工作空间资源存在性对无权限者统一返回 404。

| 表（harness schema） | 必要字段、约束或索引 |
|---|---|
| users / tenants | users 含 login_norm 唯一、password_hash、is_platform_admin、status；tenants 含 slug 唯一、status、max_running、max_workspaces、daily_token_budget |
| memberships | tenant_id、user_id 复合主键，role 为 tenant_admin/member，status。空间 owner 必须引用一个本租户成员关系 |
| auth_sessions | id、token_hash 唯一、user_id、active_tenant_id、expires_at、revoked_at、csrf_hash。平台角色和成员状态在服务端校验 |
| templates | id、version、image_digest、profile_hash、cpu、memory_bytes、pids_limit、enabled；发布后不可原地改写版本 |
| workspaces | id、tenant_id、owner_id、template_version、enabled、desired_state、observed_state、generation、auth_epoch、last_activity_at、error_code。首版唯一 (tenant_id,owner_id)，增加 unique(tenant_id,id) |
| workspace_operations | id、workspace_id、actor_id、op、idempotency_key、request_hash、state、lease_owner、lease_until、attempt、target_generation、created_at、finished_at、error_code；唯一 (workspace_id,idempotency_key)；索引 (state,lease_until) |
| entry_tickets / workspace_sessions | ticket_hash、auth_session_id、workspace_id、epoch、expires_at、used_at；空间会话存 token_hash、同样归属和撤销字段。短票只能原子消费一次 |
| runtime_credentials | token_hash、workspace_id、generation、expires_at、revoked_at；绑定运行实例，轮换时撤销旧凭据。供应商密钥不进数据库 |
| model_requests / budget_buckets | request_id、tenant_id、workspace_id、model、状态、预留量、输入/输出 token、耗时、计量来源；按 tenant + UTC 日期唯一预算桶，按 request_id 唯一结算 |
| audit_events | id、occurred_at、actor_id、tenant_id、workspace_id、action、target、result、request_id。索引 (tenant_id,occurred_at)；业务角色只追加或读授权子集 |
| 运行中会话和文件 | dsh 会话日志留在每空间独占的会话卷。项目留在项目卷。PostgreSQL 中无需复制原始推理文本或整份聊天历史 |

**权限矩阵。** 平台管理员管理租户、租户管理员和模板，可停用任意空间；租户管理员在本租户配额内管理成员、空间和用量；成员仅能进入自己名下的启用空间。管理权限本身不授予阅读成员文件、原始对话或附着终端的权限。管理员也需要个人工作空间才能使用工作台。首版空间归属不可就地转移；给另一用户分配新空间，防止遗留历史被继承。

**认证实现。** 本地账号使用 Argon2id 密码哈希，登录设有速率限制，失败返回通用错误。首次平台管理员由交互式 CLI 创建，无内置默认密码。门户与每个工作空间都使用各自的 host-only、HttpOnly Cookie，不设 Domain。本机 HTTP 仅限 loopback 开发，部署 HTTPS 时启用 Secure。改变状态的浏览器请求校验精确 Origin 和 CSRF，登录也校验 Origin；WebSocket 校验精确 Origin、有效会话、空间和 epoch。控制 API 禁止宽泛的带凭据 CORS。退出登录、切换租户、禁用用户和撤销成员要吊销相关空间会话并关闭现有连接。

## 6. 工作空间生命周期及一致性

**状态约定。** 业务开关 enabled、期望状态 running/stopped 和观测状态 provisioning/starting/running/stopping/stopped/error 分开。重建是一个有记录的操作；停用产生 enabled=false、desired=stopped。未首次启动的空间可为 stopped，尚无容器。每次替换实例递增 generation；撤权或实例更替递增 auth_epoch。

1. **分配。** 管理员提交 tenant、owner、template 和 Idempotency-Key。在单个数据库事务内锁租户配额行、确认有效成员、检查空间数、写空间和审计。默认只分配记录。用户首次进入调用 start，看到“环境准备中”。
2. **启动。** 校验配额时计入已预留但未就绪的 starting/provisioning 空间；同一事务更新期望状态、分配运行名额并写操作。worker 用 FOR UPDATE SKIP LOCKED 领取带租约的短事务任务，提交后才调用 Docker。每空间一次只允许一个变更执行。重复同 key 同参数返回原 operation；同 key 不同参数返回 409。
3. **准备资源。** 创建或复用本安装和空间标签一致的两个数据卷、internal bridge，并将 relay、llm 接入；只接受已批准的镜像 digest 和 CPU/内存/PID 配置。在只读根文件系统下预备可写 `/tmp`、项目卷和 DSH_HOME。镜像预建 UID/GID 10001 的卷挂载目录，首次验证实际所有者；需要初始化时由一次性固定命令初始化空卷。命名冲突且标签不符时退出，拒绝接管。
4. **启动与就绪。** 以固定非 root UID 运行 runtime，关闭特权、丢弃 capabilities、no-new-privileges，使用默认 seccomp、只读 rootfs、受限 tmpfs；不挂 Windows 盘、Docker socket、宿主 PID/网络或设备。镜像内预装工具，用户在项目目录创建 venv。示例规格 1 CPU、1 GiB、256 PIDs，标为起测值，M0 以实际冷启动测试校准。worker 确认 dsh、适配器、卷读写及模型代理路径后标记 running。
5. **停止。** 先拒绝新请求、撤销入口、关闭 PTY/WS、取消模型流，给正在执行的任务有限宽限期，再终止实例。释放运行名额，保留项目卷、会话卷和映射。空闲停机默认关闭；启用时，运行中的 Agent/终端/审批等待有明确保护或超时规则。
6. **重建与停用。** 重建按旧镜像或显式选择的新模板重建容器，挂原卷、换 generation 和令牌。停用后立即拒绝 API、WS 和模型请求，并排队停止。重新启用只恢复允许启动的资格。首版管理界面不提供物理删卷；删除数据走独立的离线备份、确认和保留策略。
7. **故障对账。** worker 启动时及每 15 秒比对带安装标签的实际资源、desired、generation 和在途操作。失效租约可接管；每一步在重复执行前检查资源及归属。只有持有效租约且目标 generation 最新的 worker 能更新结果。Docker 超时后先 inspect 再决定重试。停用优先于旧 start；若过期 start 已建实例，对账关闭它。未知卷、用户自己的 Docker 容器不自动清除。

**凭据续期。** worker 只为当前有效 generation 生成高熵空间令牌，控制库存摘要，runtime 仅获本空间令牌。用有效期和提前续期任务管理长时间运行的空间，例如 60 分钟有效、提前 10 分钟轮换；新旧令牌短暂交叠，适配器重载模型配置后撤销旧值。M0 若确认锁定的 dsh profile 不支持热换凭据，改用容器内回环模型适配器：dsh 指向回环固定地址，适配器在转发时从该空间独有的受限临时文件读取最新令牌；无需重启用户任务。原始供应商密钥始终在 llm 服务。停用时所有代际令牌立即作废。

**运行边界。** CPU/内存/PID 在 Docker 层实施，磁盘监测、上传大小限制和告警不能约束用户在 Shell 里持续写文件。首版把磁盘标成软限，另设 Docker Desktop 虚拟磁盘剩余空间停发策略；要求按用户强制限盘的场景须选支持每卷配额的存储后再上线。上游授权弹窗约束 Agent 工具流程，交互 Shell 本来就是用户的代码执行入口，系统边界由容器、网络和平台权限实现。[8][10]

## 7. 平台 API 与工作空间协议

下表是本项目拥有的稳定契约。原生 dsh 路由固定于镜像版本，不把它们重新定义成公共 API。门户路径挂在门户 Host；空间路径只在已绑定的空间 Host 上生效。

| 方法、路径 | 请求 / 响应核心 | 授权与要求 |
|---|---|---|
| POST /api/auth/login；GET /api/me；POST /api/auth/logout | 登录返回用户、租户列表、CSRF；me 返回当前身份 | Cookie 会话；注销级联撤销 |
| POST /api/auth/active-tenant | tenant_id → 当前租户及新 CSRF | 仅限有效成员；平台级管理走独立授权 |
| POST、GET /api/admin/tenants；PATCH /api/admin/tenants/{tid} | 创建、分页、修改配额/状态 | 平台管理员 |
| POST /api/admin/users；PUT /api/admin/tenants/{tid}/members/{uid} | 创建账号；添加成员、配置角色或停用 | 平台管理员建全局账号；租户管理员可管理本租户的已有账号；不得提升平台权限或移除最后一个有效租户管理员 |
| GET /api/templates；POST /api/admin/templates | 可用模板、注册受信任镜像版本 | 成员读可用模板；仅平台管理员登记固定 digest |
| POST /api/admin/tenants/{tid}/workspaces | owner_id、template_version → 201，重复分配由唯一约束处理 | 平台或本租户管理员；校验配额 |
| GET /api/workspaces；GET /api/workspaces/{wid} | 名称、状态、规格、本人可执行动作、错误码 | 成员只见自己的空间；管理员只见职责内元数据 |
| POST /api/workspaces/{wid}/actions/{action} | start/stop/rebuild/disable/enable → 202 + operation_id | 成员可启停本人空间；其余管理操作需管理员。要求 Idempotency-Key |
| GET /api/operations/{id} | queued/running/succeeded/failed、阶段、可重试原因 | 检查对应空间权限；前端退避轮询至终态 |
| POST /api/workspaces/{wid}/entry-tickets | target=agent/files/terminal → 201，受控表单目标、短票、过期时间 | 已就绪、本人、当前租户、CSRF；不可指定外部 URL |
| POST /_platform/enter（空间 Host） | 表单票据 → 空间 Cookie + 303 到固定页面 | 仅接受门户精确 Origin，票据绑定登录会话、租户、Host、epoch；60 秒有效，原子置 used |
| GET /_platform/files；GET/PUT /_platform/file | list(path,cursor)、读取/流式写入；ETag、If-Match | 本人空间；二进制走流式，修改写审计；新建使用 If-None-Match |
| POST /_platform/directories；POST /_platform/moves；DELETE /_platform/file | path、src/dst、预期版本；目录删除首版仅允许空目录 | 成功 200/201/204；冲突 409/412；写请求检查 CSRF |
| WS /_platform/terminal | 下文终端消息协议 | 空间 Cookie、精确 Origin、权限、并发数和运行代际校验 |
| GET /api/admin/tenants/{tid}/usage、/audit | 时间范围、空间、分页 | 本租户管理员或平台管理员；响应包含用量来源和未知项 |
| 工作空间其余上游路径 | 原生 dsh 的资产、HTTP、WebSocket、会话和确认协议 | 网关先检查 Host、票据会话、当前权限，再转发到固定 runtime |

示例：`POST /api/workspaces/{wid}/actions/start` 携带 `Idempotency-Key` 和 CSRF 后返回 `{"operation_id":"<uuid>","state":"queued","workspace_id":"<uuid>"}`。统一错误 `{"error":{"code":"WORKSPACE_NOT_READY","message":"工作空间正在启动","request_id":"<uuid>","retryable":true}}`。401 未登录、403 角色/CSRF/Origin 失败、404 无权枚举对象、409 生命周期冲突、412 文件版本冲突、413 上传超限、429 超配额、502 上游错误、503 平台暂不可用。所有网关错误避免输出容器地址、内部堆栈和凭据。

### 网关和原生 dsh 登录

- dsh 在容器内监听回环。启动模板按上游支持的方式设置对外 URL 和 trusted-host，示例 `dsh web --no-open --public-url http://w-<uuid>.localhost:8080/ --trusted-host w-<uuid>.localhost:8080`。实际端口和格式以 M0 锁定版本为准。前置适配器监听专网端口，处理平台文件/终端的内部转发和原生 Web 代理。
- 适配器作为 dsh 的父进程，在内存中捕获本次启动凭据，使用对外 Host 对回环上游完成根路径 token → 签名 Cookie 交换，禁止自动跟随未知重定向。后续 HTTP/WS 到 dsh 由适配器注入上游 Cookie，保持浏览器侧 Host、合法 Origin 和要求的子协议。平台 Cookie、Authorization 和身份头在进入 runtime 前剥除，上游 Set-Cookie 不回写平台。上游重启时重新交换。验收覆盖一次 302/303、静态资源实际路径、WS 升级和断线续连，禁止关闭上游认证绕过兼容问题。[2][3]
- 网关保留 `/_platform/` 前缀，所有其他合法路径按原始编码安全转发，过滤 hop-by-hop 头，WebSocket 显式处理升级、双向背压、断开和 ping。relay 接受服务端生成的内部目标，不接受浏览器给出的地址。签名绑定请求方法、标准化路径、目标空间、generation、短时效与 nonce；验签后去除签名。禁止跟随任意上游重定向。门户与工作台顶层切换，用户文件不能以主动 HTML/SVG 内嵌门户执行。
- 空间会话有效性绑定门户会话、活跃租户、用户、workspace、epoch 和 enabled。长连接及未完成的长传输在握手和传输期间至多每 2 秒复查，提交停用时本进程立即广播关闭；验收界限为事务提交后 3 秒。数据库不可用时拒绝新连接并关闭无法续验的旧连接。本机单网关进程用连接注册表即可；扩多副本前增加跨进程撤权通知和逐连接复查。

## 8. 用户工作台：分析、文件、终端

**页面归属。** 门户首页显示当前租户、本人空间、状态、规格和进入按钮；管理页显示租户、成员、分配、操作进度和用量。空间 Host 上 `/_platform/ui/files` 和 `/_platform/ui/terminal` 由可信平台提供 Vue 静态资产，`/_platform/me` 返回本人空间摘要和当前空间 CSRF。Agent 首页使用原生 dsh；固定的工作台导航支持往返。首次进入自动定位 `/workspace`，若上游没有稳定的预选接口，首版明确引导用户在原生选择器选中该目录；首次验收记录采用哪种方式。

**浏览器请求兼容。** 平台自建表单/API 使用同步 CSRF token。原生 dsh 的变更请求如无法附加平台自定义头，专用空间 Host 走精确 Origin 校验、独立 SameSite 会话、仅允许锁定原生协议的内容类型与方法，保留上游认证与其自身校验；拒绝无 Origin 的浏览器写请求和跨源上传。入口票据的跨域表单 POST 是唯一明确允许的门户 → 空间写入，且依赖短票；票据兑换后再从空间域设置 Cookie。M0 记录原生请求/WS 实际形状，验证来自另一空间页面的写入失败。

**过程显示与恢复。** 以一次用户输入为一轮，以模型请求与随后的工具调用为一个步骤，界面按实际因果顺序呈现。下表为 UI 语义，标签不是上游事件 API。M0 把锁定版本中的事件名、真实脱敏样本和前端组件映射提交到 `contracts/upstream/`。

| 用户看到的内容 | 数据来源与完成条件 |
|---|---|
| 任务计划、待处理问题 | 仅在模型或规划工具实际给出计划/问题时显示；提示不足时支持补充输入 |
| 可折叠分析、正文 | 展示模型接口实际公开的分析字段或公开摘要，与最终答复分区；模型未提供则仅展示已发生的步骤和工具证据 |
| 已调用工具 | 显示工具名、可展示的参数、目标文件、运行状态；用 invocation ID 对应结果，失败也保留 |
| 命令输出和文件差异 | 展示限制长度的 stdout/stderr、退出码、用时。文本变更优先使用工具提供的前后文本；必要时通过插件对被编辑文件取有上限的前后快照并生成 diff。Shell 任意写入只标记可观察到的变化，二进制显示文件元数据 |
| 需要确认、取消、重连 | 展示真实的待批准操作、作用范围和批准/拒绝；同一请求只决议一次。关闭浏览器与主动取消是不同动作。重新打开从持久会话恢复已结算记录，再接实时流 |
| 中断与重试 | runtime 重启时，会话中已提交的事实可恢复；未落盘片段允许缺失，未确认结果记为中断/未知。用户明确重新提交后才允许重做有副作用的操作 |

用 workspace-scoped session/turn/tool ID 关联。对于上游缺少的显示项，实现会话插件和对应 Vue/原生渲染扩展，只保存有用户价值的脱敏记录。平台审计单独保存在控制库，容器内用户可修改的会话文件不能承担可信审计职责。审批用于限制 Agent 的自动动作；用户手动打开 Shell 本身是已有权限的一部分。

**文件实现。** 容器内 Python 文件服务使用 Linux 相对路径，以打开的 `/workspace` 目录 FD 为根。逐级用 dir_fd 和 O_NOFOLLOW 访问目录，拒绝符号链接、绝对路径、父目录、NUL、设备和非普通文件；源和目标均校验，只解码一次。下载用已打开文件 FD 流式读取；写入相同目录的临时文件，成功后 fsync、原子替换，断流清临时文件。编辑器取得文件内容与版本（小文本用字节 SHA-256）；保存发送 If-Match，外部修改后提示重新加载并显示差异。文件 API 内写操作按空间+路径串行，重命名同时锁源/目标。终端和任意第三方进程可绕过应用锁，文档和测试只承诺检测保存时已可见的修改；不能宣称对任意外部写入有强事务保护。编辑器首版 UTF-8，超过 2 MiB 或二进制只下载。默认上传单文件 128 MiB，验证实际累计字节，列表每页 100；下载添加 attachment 与 nosniff。UI 删除前确认；无递归删除入口。

**终端实现。** 浏览器用 xterm.js + FitAddon，容器内 Python 用 pty/fork + setsid 或等效 PTY 库运行受控默认 Shell，cwd=/workspace，非 root；环境采用白名单。浏览器传二进制 stdin，服务传二进制原始 PTY 输出；文本控制帧示例 `{"type":"resize","cols":120,"rows":36}`，关闭消息带退出码，Ctrl+C 透传 0x03。每空间默认最多 2 个终端，单连接有大小上限和背压；普通终端断开后结束本次进程组并回收子进程；Agent 后台任务由 dsh 生命周期管理。终端会话审计只记谁、何时、何空间和退出状态。日常使用能运行容器预装程序、创建项目文件和进程；额外系统包由管理员制作新版镜像，主机 Windows 文件和管理权限独立。

## 9. DeepSeek 集成、流式工具调用与预算

**接入参数**与用户提供的方式一致：上游 `https://api.deepseek.com`、模型 `deepseek-flash`、`reasoning_effort="high"`、`thinking.type="enabled"`。容器内 dsh 的端点设成 `http://model-proxy:8090/v1`，凭据为仅限当前工作空间及运行代际的短期随机令牌。构建时预置可审查的 dsh profile/模型配置，按上游已验证的配置面登记路由和模型，启动时注入空间令牌。代理拒绝任意模型、外部 URL、未经允许的上游功能；自定义端点、插件安装、遥测和附加会话日志上传在模板中逐项审阅，仅保留这次交付的能力。实际必须由网关、网络和配额保证边界，即使用户在空间里修改自己的配置或直接调用代理也不能扩大授权。[4]–[6]

**先跑非流式探针。** 这是由 Codex 实现为 `scripts/deepseek_smoke.py` 的最小逻辑，读取本地环境变量。默认离线测试不执行它。真实密钥只用于维护者启用的 live 测试和模型代理运行，不写入测试 fixture。

```python
import os
from openai import OpenAI

client = OpenAI(
    api_key=os.environ["DEEPSEEK_API_KEY"],
    base_url="https://api.deepseek.com",
    timeout=45.0,
    max_retries=0,
)
reply = client.chat.completions.create(
    model="deepseek-flash",
    messages=[
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Reply with OK."},
    ],
    stream=False,
    reasoning_effort="high",
    extra_body={"thinking": {"type": "enabled"}},
)
print(reply.choices[0].message.content)
```

**模型代理最小协议。** `GET /v1/models` 只列已授权模型；`POST /v1/chat/completions` 同时支持普通 JSON 和 SSE。上游 URL 固定映射至官方 `/chat/completions`，替换 Authorization，移除转发头和客户端自选密钥。使用异步 HTTP 客户端流式转发供应商支持的字段，保留 `reasoning_content`、`content`、工具索引/ID、函数参数分片、finish_reason、usage 及 `[DONE]`。工具 schema 和回传工具结果经验证后保留。工具必须在空间运行；模型代理不执行命令。M0 记录 dsh 实际发出的协议格式，若默认使用别的供应商协议，明确选 OpenAI Chat Completions 路由或写薄适配；不做半兼容的格式翻译。

**多轮与取消。** 携带 tools 时按当前 DeepSeek 协议保留并回传既有 assistant 消息所需的 reasoning_content 和 tool_calls，以 tool_call_id 关联 tool 结果；仅供 UI 展示的摘要不进入替代位置。断流后显示失败或中断。上游已开始生成、发出工具调用或结算状态未知时禁止透明重放。用户主动取消时关闭上游流、取消可取消的子任务并记录成功、失败或结果未知；单纯的浏览器断线只影响显示订阅。给首字节、读空闲和总时长分别设置可配置上限。对 401/403、429、5xx、超时、无可用模型给出可诊断的分类错误。[6]

**用量与并发。** 模型账户由 tenant_id/workspace_id/generation 从服务端凭据推导；默认每空间同时 1 次模型调用，租户上限可配。使用数据库事务锁定预算桶，按固定上限预留输入加最大输出，拒绝越限请求，再调用上游。对输入没有可信 tokenizer 时采用保守上界或明确限制为软预算；硬预算不得依赖不可靠的估算。若实现硬 token 预算，最简单的首版保守方案是按已验证输入上界和明确的 max_tokens 设置预留，总上界超预算就拒绝。结束后用供应商实返 usage 结算；usage 缺失记 unknown 并保留保守预留，后台对账后再释放。请求唯一 ID 防重复计费，过期并发租约与余额预留分别处理。代理重启不把未知请求当成免费。撤权时最长每 2 秒查令牌状态并关闭正在转发的流。仅记录 token 数、延迟、状态、用量来源，不记录完整模型报文。

## 10. 仓库结构、启动与测试入口

下表是要求 Codex 创建的仓库契约。Python 建议 FastAPI、SQLAlchemy 2、Alembic、psycopg 3、httpx、pytest；前端 Vue 3 + TS、Vite、Element Plus、xterm.js、文本编辑/diff 组件、Vitest、Playwright。Compose 使用项目专属名称。M0 选兼容版本，随后提交 Python 与 npm/pnpm 锁文件。

| 路径 | 产物 |
|---|---|
| apps/portal/ | 门户、租户管理、空间管理、文件与终端页面、路由守卫；生产静态包 |
| services/api/ | 认证、授权、管理、网关、操作与审计 API、OpenAPI；共享输入模型 |
| services/worker/ | DockerRuntimeDriver、操作队列、租约、探活、对账、资源标签和恢复 |
| services/relay/、services/llm/ | 受控 HTTP/WS 转发；模型代理、预算、流式转发和用量 |
| runtime/base/、runtime/plugins/ | 固定镜像、dsh profile、进程监督、启动交换凭据、文件/PTY 服务、补充事件插件 |
| db/、migrations/ | 专用角色/schema 引导、版本迁移、授权、独立测试环境检查 |
| infra/、compose.yaml | Nginx、各服务 Dockerfile、网络、健康检查、secrets、日志限额和开发配置 |
| scripts/ | PowerShell 统一入口、冒烟测试、备份/恢复、诊断；运行前验证安装 ID 和目标环境 |
| contracts/、tests/ | API 契约、锁定上游脱敏样本、单元/集成/E2E、离线假模型与权限矩阵 |
| README.md、upstream.lock.json、docs/verification.md | 真实启动步骤、版本证据、执行过的测试与失败记录 |

**本机操作顺序。** 下列命令是仓库完成后的验收入口；脚本须支持带空格的路径、UTF-8 文件和重复运行。Codex 应先实现命令再在 README 标注可用。docker compose config 的输出可能包含秘密，诊断仅做静默校验。

```powershell
Copy-Item .env.example .env.local
.\scripts\init-local.ps1
# 使用本机 psql 的交互口令提示运行一次角色/schema 引导
psql -h 127.0.0.1 -p 5432 -U postgres -d postgis -W -f .\db\bootstrap.psql
.\scripts\doctor.ps1
.\scripts\build.ps1
.\scripts\migrate.ps1
.\scripts\admin-create.ps1
.\scripts\up.ps1
.\scripts\test.ps1 -Suite offline
.\scripts\test.ps1 -Suite integration
.\scripts\test.ps1 -Suite e2e
# 本机已配置有效的 DeepSeek 密钥时运行，会产生实际 API 用量
.\scripts\test.ps1 -Suite live
.\scripts\down.ps1
```

init-local 只补缺失配置；首次复制后不要覆盖已有 .env.local。doctor 将镜像构建前的主机检查与构建后服务探针分开：首次用固定版本诊断容器测试 PG，首次无镜像时显式说明需要拉取。build 构建控制服务与 runtime，记录可信镜像 ID/来源；本地无 registry 时以 Docker 本地不可变 image ID 启动，发布到 Harbor 后改用 repo@sha256:digest。migrate 用单次 owner 容器，admin-create 用一次性 app CLI 交互输入管理员密码。up 只启动已配置服务并等待 readiness，首次打开 `http://portal.localhost:8080`。down 先停止当前安装的工作空间再停控制服务，保留卷；脚本禁止使用全局 prune 或 down -v。测试脚本对 test schema、Compose 项目名、资源标签、卷前缀及测试入口端口做交叉校验，默认不连接真实模型。PowerShell 使用 docker compose --env-file .env.local，并确保容器只接收自己需要的变量。

**测试替身。** 离线模型实现同一 /v1 接口，按固定剧本返回分片分析、分片工具参数、工具结果后的最终 JSON、usage、超时或 429。集成测试使用真实 Docker、PostgreSQL、dsh 和假模型；E2E 驱动真实浏览器；live 在本机通过真实模型代理复跑最小消息和一次工具往返，限制最大轮数、输出和用量。假模型通过不等同于真实模型通过。

## 11. Codex 分阶段执行单

按阶段合并，每个阶段输出变更文件、可运行命令、真实测试结果和剩余问题。不要一次生成整套空页面、接口桩，再统一宣称完成。多个阶段共用 M0 确定的契约。

| 阶段 | 可提交成果 | 进入下一阶段的条件 |
|---|---|---|
| M0　打通最难链路 | 建最小仓库、版本锁、一个临时空间、固定 profile；连通真实 PG；用假模型跑原生 Web；验证实际模型配置和登录交换；检查 :8080 Host、WS、命令、编辑、刷新；若有密钥加一次真实工具往返 | 提交版本清单和脱敏输入输出样本。Agent 确实在容器写出文件，Windows 读到的数据库为预期实例。未提供 live 条件时明确标记待测 |
| M1　身份和元数据 | 角色引导、迁移、平台登录、租户/成员管理、配额、基础 Vue 管理页和授权测试 | A/B 两租户与三个账户通过矩阵测试；数据库 diff 只包含项目 schema |
| M2　可恢复的容器分配 | worker、幂等操作、动态网络、双卷、模板、状态轮询和管理界面 | 并发启动只建一个实例；worker 中断重启能收敛；停用不丢文件 |
| M3　进入空间与真实会话 | Host 路由、一次性票据、WS 网关、dsh 适配器、模型代理、授权和预算 | 两个空间可同时独立对话；拒绝跨空间 HTTP/WS；撤权能关闭长连和模型流 |
| M4　操作系统与执行可视化 | 文件树/编辑/上传下载、PTY、过程时间线、批准/拒绝、取消、历史和差异查看 | 示例 GeoJSON 任务在网页完成；手动编辑和 Agent 输出互相可见；刷新能恢复 |
| M5　交付验收 | 异常恢复、三账户 E2E、备份恢复、容量基线、排障手册、干净检出演练 | 表 12 的 P0 全部通过；未运行项列明。若发布目标含真实 DeepSeek，则真实链路必须通过 |

**给 Codex 的首条任务指令，可与本文一起提交。**

> 阅读本手册，在当前仓库先检查现有代码和 AGENTS.md，保留已可工作的能力。先实现 M0，交付可运行验证程序、锁定版本、脱敏契约样本和结果；随后按 M1–M5 持续实现、运行测试并修复。每一阶段都从用户实际入口验收。对接本机数据库只操作专用 schema，测试用独立资源；所有真实密钥从本机环境读取。对于无法在当前环境执行的 Windows、Docker Desktop 或实际模型测试，交付可运行脚本并记为待现场验证。以第 12 节的结果决定完成度，不得用 Mock 结果代替真实集成结论。

## 12. 测试与验收矩阵

测试种子：平台管理员 P；租户 A 的租户管理员 TA、成员 A1/A2；租户 B 的成员 B1。另给 A1 一个 B 租户成员身份，用来覆盖“同一账号切租户”。准备同名文件但内容不同的 A1/A2/B1 工作空间、固定三点 GeoJSON 和一个 128 MiB 边界测试生成器。所有后端断言在 UI 隐藏按钮之外，直接调用同一个受保护入口核验。

| 编号 | 测试操作 | 必须观测到的结果 |
|---|---|---|
| T01 P0　环境 | 在新检出目录运行第 10 节；启动脚本跑两次 | 相同服务和迁移版本，无重复租户/管理员，项目外数据库表、卷和容器无变动 |
| T02 P0　角色 | TA 给 A1 分配；TA 请求 B 的操作；P 尝试读 A1 文件；A1 切到 B 后用旧 A 链接 | 合法分配成功；越权操作均失败；旧会话按时撤销 |
| T03 P0　隔离 | A1 尝试使用 A2/B1 的已知文件、历史、会话、终端、WS、operation_id 和 entry-ticket；同名文件对照 | 所有资源均校验实际归属；本人看正确内容；其他空间凭据不被接受 |
| T04 P0　入口票据 | 双标签页消费同一票、过期票、错 Host/Origin、直接访问原生上游、退出后重开旧页 | 单次仅一成功；工作空间页收不到平台 Cookie；浏览器不能直达 runtime；退出后访问失败 |
| T05 P0　并发配额 | 同一 start 请求并发 10 次；空间数仅余 1 时两个用户并发启动 | 相同幂等键返回同一操作；仅一个运行实例或最后一个有效名额，无脏预留 |
| T06 P0　网络/权限 | 用实际 runtime 验证仅接指定网络；探测测试夹具的受控拒绝目标：另一空间服务、Docker、宿主 PG、测试外网端点；核查 uid、mounts、capabilities | 非 root、双卷独立；上述拒绝目标不可用；仅允许的模型通道可达。若该 Desktop 版本仍能访问宿主，阻断规则实测通过后方可通过此项 |
| T07 P0　文件 | 上传中文/空格文件、建目录、改名、下载比哈希；测试父目录、符号链接、并发改动、上传断开和大小边界 | 内容哈希匹配；越界拒绝、冲突 412、超限 413；无截断的可见目标文件，无临时文件积累 |
| T08 P0　终端 | 输出 Unicode、交互读入、执行 sleep 后 Ctrl+C、resize、退出；停用时留一终端打开 | 能输入、中断、调整尺寸；退出后回收进程；停用后 3 秒内关闭且不能重连 |
| T09 P0　模型 | 假模型分片工具请求 → 容器执行 → 工具结果 → 最终答复；再用真实模型做一次小任务 | 有可核对的工具 ID、实际输出、正文和分析显示；usage 归属正确；live 通过须有真实 request_id 或等价脱敏凭据 |
| T10 P0　审批/取消 | 触发模板中需批准的测试动作，分别拒绝和批准；取消受控的长任务 | 拒绝时没有对应文件变更；批准一次执行一次；取消后任务结束，前端显示实际结果 |
| T11 P0　恢复 | 任务中刷新；正常停止、重建同一空间；有副作用的命令执行中强停 runtime | 已落盘会话/文件仍在；断线不重复提交；未知结果显示中断，不自动重放命令 |
| T12 P0　故障 | 在建卷后重启 worker；启动失败；Desktop 未启动；数据库失联；反复停用/启动 | 可对账并恢复，操作无永久卡住，启动失败释放名额；撤权后没有陈旧 worker 重新启用空间 |
| T13 P0　模型异常 | 注入 401、429、超时、流中断、缺 usage；多个空间同时使用租户预算 | 显示正确分类；不泄密、不重复计费；预算预留、未知用量和并发名额按规则处理 |
| T14 P0　完整业务 | A1 上传三点 GeoJSON，让 Agent 生成 result.json，检查时间线、终端、下载和恢复 | 浏览器全流程通过；统计含 count=3；包围盒与 fixture 精确比对；A2/B1 无法获取结果 |
| T15 P0　运维交付 | 停止后备份 DB 与双卷，恢复到隔离测试实例，重新启动并重做 T14 的读取步骤 | 文件 SHA、历史、所有者映射正确；旧 Cookie/模型令牌失效，无生产数据覆盖 |
| T16 P0　日志与内容 | 使用合成标记模拟密钥，扫描网关/worker/浏览器控制台/测试报告；下载 HTML/SVG；发跨源写请求 | 合成秘密不出现在日志或构建资产；主动文件只下载或安全文本化；写请求校验 CSRF |
| T17 基线　容量 | 冷启动和热启动各至少 5 次；1/2/4 个空间依次运行固定短任务；若配额或内存不足，记录止点 | 报告宿主机配置和 Desktop 资源、就绪耗时中位数/最大值、每空间空闲与峰值内存、首个流事件延迟、失败率和磁盘增长 |

离线用例应能在无 DeepSeek 密钥时通过；有费用的 live 套件单独执行。测试记录至少包含版本/环境、fixture 名、命令、退出码、通过/失败/跳过数量、失败断言和重试结果。提交可复跑的脱敏报告，不以截图代替断言。runtime、worker 或 gateway 改动后重跑 T03–T13。初始资源数值是工程假设，容量上限由 T17 实测决定。

## 13. 备份、恢复、维护和故障诊断

**备份与恢复。** Codex 实现 `backup.ps1` 和 `restore.ps1 -Target test`。本机首版采用维护窗口备份：暂停工作空间变更、停止各 runtime 并清空在途操作，保持控制库的业务写入冻结，用 pg_dump 自定义格式导出目标 schema；记录角色/授权重建脚本、镜像标识、模板、卷映射及 upstream.lock。用受信任、只读挂卷的辅助容器分别归档项目卷和 DSH_HOME，并计算校验和。备份可能含用户会话和已失效的空间令牌，限制访问、加密存放。恢复时用独立实例或独立数据库、项目名和卷，先还原角色和元数据，再还原两卷并校验归属/哈希。清空恢复副本中的浏览器会话、票据及在途租约，撤销旧令牌、递增 epoch、从 stopped 对账后再恢复服务。按逻辑空间 ID 找卷，不能依赖旧的 Docker 容器 ID。实际恢复演练是验收项。

**运行诊断。** 每个请求贯穿 request_id，每个后台操作有 operation_id 和 generation。提供 liveness、readiness 及仅管理员可读的分项诊断；ready 区分 DB 连接、引擎可用、模板镜像、运行时和模型探针。模型临时不可用时门户仍可登录和下载文件。日志按大小轮转；记录空间状态转换、授权失败、容器退出原因和模型错误类型。模型计量与普通日志都不采集终端原文和对话内容。

| 症状 | 最短定位步骤 |
|---|---|
| Windows 可连数据库，容器超时或认证失败 | 分别测主机与应用容器；确认 host.docker.internal、真实来源与监听；区分超时、HBA 拒绝、口令失败和 schema 权限失败 |
| 已登录，工作台 401/403 或循环重定向 | 对照浏览器 Host/Origin、trusted-host、公网 URL、票据 epoch、根路径交换和 Cookie 作用域；检查转发没有把平台 Cookie 注入上游 |
| 页面打开但无流式输出 | 区分浏览器 WS、网关升级、dsh 事件、模型 SSE；禁用 SSE 代理缓冲，合理设置读空闲超时；用有时间间隔的假模型分片验证首片即时可见 |
| 分配停在 starting 或模板启动失败 | 查看 operation_id、worker 租约、指定镜像 ID、UID、双卷权限、runtime 就绪探针、relay/llm 网络 attachment 和 Node 内存 |
| gateway/llm 重建后已有空间不可达 | worker 按服务当前容器 ID 对账，重新连接所有启用空间网络，恢复唯一 runtime 别名，再逐个探活；不可依赖旧服务容器 ID |
| 结果不见或会话丢失 | 核对 workspace_id、generation、项目卷和 DSH_HOME 卷标签；确认历史已提交、同一模型 profile、没有误挂空卷 |
| 模型 401、没有工具调用或工具回传 400 | 分清空间令牌与供应商密钥，对照 DEEPSEEK_BASE_URL、实际模型名、tools、tool_call_id、reasoning_content 和分片拼接；只输出脱敏元数据 |

**后续迁移。** 让 worker 依赖 RuntimeDriver 的 ensure/start/stop/rebuild/inspect/attach_gateway 接口，业务层只读逻辑工作空间 ID。迁到 Kubernetes 时将租户映射为 Namespace、空间映射为 Pod 和独立 PVC，镜像由 Harbor 提供。重验 CNI 的默认拒绝和受控出口、资源配额、容器安全上下文、撤权、卷快照、一致性与备份。外部客户可运行不受信任代码时，单独选择和验证沙箱运行时或虚拟机级隔离。Docker Desktop 本机通过是开发里程碑；多节点和对外开放需要单独验收。[8][11]

## 14. 官方资料与核验范围

以下资料用于确认上游接口、隔离机制与部署约束。平台表名、业务路由、资源规格、验收阈值是本方案的实现决策。上游 master 会变化，复现以 M0 锁定的 commit 为准。

1. DeepSeek Harness 项目、许可和开发预览状态。[官方仓库](https://github.com/deepseek-ai/deepseek-harness)
2. 原生工作台、反向代理、Host 与 Cookie 约定。[Web 入门](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/user/guide/index.md) · [代理部署](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/user/guide/public-deployments.md)
3. 运行时架构、会话事件和 Web 登录交换。[架构](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/architecture.md) · [连接组件](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/client/connection/README.md)
4. 模型路由、端点和凭据配置。[模型配置](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/user/guide/providers.md)
5. SDK 工作目录、DSH_HOME、工具配置及本地执行边界。[Python SDK](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/user/guide/python-sdk.md)
6. DeepSeek 模型名、思考模式、流式响应和工具调用。[模型说明](https://api-docs.deepseek.com/quick_start/pricing/) · [Thinking Mode](https://api-docs.deepseek.com/guides/thinking_mode/) · [Tool Calls](https://api-docs.deepseek.com/guides/tool_calls/)
7. Windows Docker Desktop 的主机访问方式。[Docker Desktop 网络](https://docs.docker.com/desktop/features/networking/networking-how-tos/)
8. Docker Engine 权限和 internal 网络。[Engine 安全](https://docs.docker.com/engine/security/) · [网络创建](https://docs.docker.com/reference/cli/docker/network/create/)
9. PostgreSQL 连接控制和 schema 权限。[pg_hba.conf](https://www.postgresql.org/docs/current/auth-pg-hba-conf.html) · [Schemas](https://www.postgresql.org/docs/current/ddl-schemas.html)
10. DeepSeek Harness 自身的安全边界。[上游安全说明](https://github.com/deepseek-ai/deepseek-harness/blob/master/SAFETY.md)
11. Kubernetes 多租户隔离的部署条件。[Kubernetes Multi-tenancy](https://kubernetes.io/docs/concepts/security/multi-tenancy/)
