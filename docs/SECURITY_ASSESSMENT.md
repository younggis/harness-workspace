# 安全评估与合规证据包（内部自评）

状态：内部自评与证据整理已完成；**第三方渗透测试、SOC 2 正式审计、DPA 需外部机构/法务**，不在本机可完成范围。

## 1. 评估范围

- 控制面：API / worker / relay / llm / edge / portal
- 数据面：每空间运行时容器（dsh + 适配器 + 文件服务 + PTY）
- 认证：本地账号、OIDC、MFA、SCIM、API token
- 数据与密钥：harness schema、Docker secrets、日志脱敏

不在范围：宿主 Windows PG 自身配置、既有 GIS 表/public schema、其他 Docker 项目、企业 IdP 实际基础设施。

## 2. SOC 2（Trust Services Criteria）初步映射

| 控制 | 实现 | 证据 |
|---|---|---|
| CC1 控制环境 | 角色（平台/租户管理员/成员/服务账号）、细粒度 11 项权限 | `docs/REQUIREMENTS.md` FR-1/2、`tests/test_rbac.py` |
| CC2 沟通与信息 | 审计事件链、request_id、错误包络 | `docs/verification.md` 1.x |
| CC3 风险评估 | 威胁模型、隔离渗透、极端条件测试 | `docs/DESIGN.md` 第 9 节、1.23/1.29 |
| CC5 控制活动 | 配额、租约队列、对账、CSRF/Origin、签名 | 1.34 P0、1.35 P1 |
| CC6 逻辑与物理访问 | Argon2id、OIDC PKCE、TOTP、会话过期、撤权广播 | 1.1–1.14、1.21、1.35 |
| CC7 系统运行 | health live/ready、指标告警、备份/PITR、孤儿网络 GC | 1.15/1.16/1.22/1.34/1.37 |
| CC8 变更管理 | 迁移版本、模板不可变、升级门禁、CI | `docs/upgrades.md`、1.14、1.37 |
| CC9 风险缓解 | 隔离网络、cap_drop/只读根、密钥扫描 | 1.23、1.35、`SECRET_SCAN_CLEAN` |

## 3. 渗透测试自查清单（可交给第三方作 scope）

| 领域 | 测试点 | 本地已验证 |
|---|---|---|
| 认证 | 弱口令/爆破/限流、会话固定、JWT/OIDC state、MFA 绕过 | 1.29、OIDC E2E（P5 本地 mock IdP） |
| 授权 | 跨租户越权、IDOR、角色提升、scope 绕过 | 1.29、1.35 |
| CSRF | 仅 Cookie 写请求、Origin 校验、跨主机表单 | 1.35、票据 Host/Origin 绑定 |
| 文件 | 路径穿越、符号链接、绝对/空路径、超大文件、ETag | 1.29（19/19 容器探针） |
| 容器逃逸 | 非 root、只读根、cap_drop、no-new-privileges、无 docker.sock | 1.23 三空间 ISOLATION_PASS |
| 网络 | 跨空间可达性、外网/宿主 PG、默认 bridge | 1.23、1.29 跨空间 IP 不可达 |
| 密钥 | 仓库/镜像明文、日志泄露、轮换 | `SECRET_SCAN_CLEAN`、1.35 |
| 输入 | 畸形 JSON、超长字段、非法 UUID、未知 action | 1.29、1.34（409 而非 500） |

## 4. 证据索引

- 全流程验收：`docs/verification.md` 1.28
- 极端条件：1.29
- P0/P1/P2/P3 加固：1.34–1.37
- 隔离探针：`scripts/runtime_isolation_probe.py`、`scripts/fileservice_probe.py`
- 备份/PITR：`scripts/backup.ps1`、`restore.ps1`、`pg-pitr-drill.ps1`
- OIDC 本地端到端：`scripts/oidc-e2e.ps1`（mock IdP + PKCE/JWKS/nonce/JIT）
- HTTPS 本地端到端：prod nginx 配置 + 自签名证书，TLS 1.2/1.3 + HSTS 实测

## 5. 仍需外部完成

1. 由具备资质的第三方执行渗透测试并出具报告
2. SOC 2 Type I/II 审计（需审计机构、期间证据采样）
3. DPA/隐私政策与法务评审
4. 真实企业 IdP 联调（P5 本地 mock 已验证协议路径，真实配置仍需现场）
5. 受信任 CA 证书与生产域名（P5 本地已验证 TLS/HSTS 路径，证书为自签名）
