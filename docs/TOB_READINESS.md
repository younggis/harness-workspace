# 面向 toB 产品的就绪度评估与路线图

本文件回答“当前系统是否已经是可以卖给企业的产品”。结论先说：**当前是可运行的开发里程碑（M0–M5 本地闭环），不是可直接交付的 toB 产品**。下面按域列出差距与实施措施，优先级 P0（对外前必须）/P1（规模化必须）/P2（竞争力）。

## 1. 身份与访问（P0）
现状：本地账号 + Argon2id + 进程内登录限流；Cookie 会话；平台/租户两级角色。
差距与措施：
- ~~无企业 SSO（OIDC/SAML/LDAP）与 SCIM 自动开通~~ → OIDC Authorization Code + PKCE 与 **SCIM 2.0** 均已实现；真实 IdP 联调待现场。SAML / LDAP 仍缺
- ~~无 MFA~~ → **TOTP MFA 已实现**（迁移 0005 + enroll/verify/disable/complete，已启用用户密码后需二次验证）；WebAuthn 与管理操作强制二次验证仍缺
- 密码策略弱（仅长度）→ 复杂度、历史 password、定期更换、锁定阈值持久化（当前限流在进程内，重启失效）
- 会话不能按用户列举/吊销 → 已新增 `GET /api/admin/users/{uid}/sessions`、`DELETE /api/admin/sessions/{sid}`；退出/停用/切租户已广播关闭长连
- ~~无服务账号/API Token~~ → SCIM 2.0 bearer token 已实现（`scim.py`，服务端到服务端）；服务账号 scope 仍待做
- ~~角色过粗~~ → 11 项细粒度 permission + 角色映射已实现（`permissions.py`），已在管理端点强制；成员级 files:write 等待细化

## 2. 多租户与隔离（P0）
现状：租户/成员/空间三层模型有效；每空间独立容器、卷、网络；跨租户返回 404。
差距与措施：
- ~~运行时隔离未做渗透验证~~ → **T06 已自动化**（`runtime_isolation_probe.py` + integration 断言）；实测发现并修复了 runtime 误接默认 bridge 的重大漏洞，现在仅接入内部专网，宿主 PG/外网均不可达，model-proxy 可达；gVisor/Kata 作为高安全档仍可选
- 网络出口策略固定但无租户级策略 → 增加 allowed_egress 配置，由 llm/relay 强制，runtime 默认无外网
- 硬磁盘配额未实现（软限）→ 选支持 per-volume quota 的存储（如 CSI），或 Docker Desktop 之外用 LVM/btrfs 子卷
- 租户生命周期不完整 → onboarding wizard、暂停/恢复、数据导出与销毁流水线（含备份清理）
- 数据共享/跨租户协作首版不支持，需明确写入合同

## 3. 安全与合规（P0）
现状：密钥从 .env.local 注入；审计事件表；脱敏扫描；镜像 digest 锁定。
差距与措施：
- ~~密钥管理用 .env 文件~~ → **Docker secrets 支持已实现**（`<NAME>_FILE` + `compose.prod.yaml` + `init-secrets.ps1`）；Vault/云 KMS 与自动轮换仍缺
- ~~传输加密：本地 HTTP → 生产 HTTPS/HSTS~~ → **生产 HTTPS/HSTS 配置已实现**（`nginx-prod.conf` + `compose.prod.yaml`，静态验证通过）；真实证书与端到端 TLS 验收待现场
- 静态加密：PG TDE/卷加密、备份加密存放
- 供应链：镜像签名（cosign）、SBOM、漏洞扫描（Trivy）作为升级门禁
- 审计不可篡改：append-only 表 + 哈希链或 WORM 存储；接入 SIEM
- 数据保留与删除：PII 清单、保留期、删除请求工单、备份中的数据清理
- 合规证据包：SOC2/ISO27001 控制映射、变更记录、访问评审

## 4. 可靠性与运维（P0/P1）
现状：单 API/worker 进程；租约队列；对账；健康检查；备份/恢复脚本已实现（需演练）。
差距与措施：
- ~~单点 → API 多副本 + 跨进程撤权通知（Redis pub/sub）~~ → **Redis pub/sub 跨进程撤权已实现**（`ConnectionRegistry` + `compose.prod.yaml` redis 服务），两副本真实端到端待验证；worker 多副本依赖租约已具备
- ~~PG 单点 → 托管 PG/主从 + 自动故障转移；备份 PITR~~ → **PITR 能力已验证**（`compose.pg.yaml` + `pg-pitr-drill.ps1`，独立 PG16 演练通过）；现有生产 PG 的主从/故障转移仍需维护者系统级配置，未实施
- 备份恢复演练（T15）→ 用隔离数据库 + 测试卷前缀跑通，校验文件 SHA 与会话失效
- 滚动升级：新模板注册 → 逐空间 rebuild → 保留旧镜像回滚；upgrade-check 已落地，需在网络恢复后验证
- SLO/告警：就绪探针细分 DB/Engine/镜像/runtime/模型；指标暴露 Prometheus；告警到值班
- 日志轮转与脱敏：已部分，需集中日志与保留策略
- 容量基线 T17、故障演练 T12、模型异常 T13 纳入发布门禁

## 5. 产品体验与商业化（P1）
现状：门户/管理台已具备基本交互，刚完成卡片化改造。
差距与措施：
- 自助 onboarding：注册→验证→创建租户→邀请成员→分配空间向导
- 用量与账单：按租户/空间/模型汇总，预算告警、超额策略、发票数据导出
- 管理能力：成员批量导入、角色模板、审批策略配置、模板市场、空间规格自助选择
- 工作台：会话历史搜索、任务取消/重试、文件 diff、终端多标签、通知中心
- 多语言、无障碍、响应式
- 文档与 support：管理员手册、用户手册、API 文档、状态码说明

## 6. 部署形态（P1）
现状：Docker Compose 单机；_compose.prod_ 尚未产出。
差距与措施：
- 生产 compose：0.0.0.0 + 反代 + TLS + 防火墙规则 + 非 root + seccomp
- Kubernetes：Namespace=租户、Pod=空间、PVC=双卷、NetworkPolicy、HPA、PodSecurity、Harbor 镜像
- 多节点调度、镜像预热、存储选型、跨区容灾

## 已完成（本轮）
- 平台审计 `GET /api/admin/audit`（可按租户/动作过滤）
- 用户生命周期 `PATCH /api/admin/users/{uid}`（停用级联撤销会话/成员）
- 会话管理 `GET /api/admin/users/{uid}/sessions`、`DELETE /api/admin/sessions/{sid}`
- 备份 `scripts/backup.ps1`：pg_dump 自定义格式 + 双卷归档 + SHA256 + manifest
- 恢复 `scripts/restore.ps1 -Target test`：仅隔离数据库，校验 checksum，清会话/票据、epoch+1、从 stopped 恢复
- 连接注册表与 2s 撤权、生命周期唯一约束、契约样本与升级门禁（见 verification 1.12–1.14）

## 发布门槛（建议）
1. P0 全部有真实测试报告（T01–T17 + 渗透 + 恢复演练 + 容量）
2. SSO/MFA、密钥管理、HTTPS、审计不可篡改、备份恢复演练通过
3. 升级门禁跑通：候选 dsh 版本构建 + 契约测试 + 逐空间 rebuild 回滚演练
4. 法务/合规材料：DPA、隐私政策、SOC2 路线图

当前离“可对外销售”仍需完成上述 P0 多数项，尤其是 SSO、密钥管理、HTTPS、渗透测试、备份恢复演练、多副本与升级门禁网络验证。
