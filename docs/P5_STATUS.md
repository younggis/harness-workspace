# P5 待验证项 — 本地可验证部分执行报告

日期：2026-11-20 · 结论：**5 项中 3 项已用本地真实环境完成验证，2 项因外部机构/系统授权仍待现场**。

| 项 | 本地结果 | 仍需外部 |
|---|---|---|
| 真实 IdP 联调 | ✅ 本地 mock IdP + 隔离 API 完成完整授权码 + PKCE + JWKS + nonce + JIT 端到端：`OIDC_E2E_PASS oidc.e2e@example.com` | 企业 IdP 的 issuer/client/secret 与真实用户登录 |
| 受信任证书 HTTPS | ✅ 用生产 nginx 配置 + 现有证书完成 HTTP 301→HTTPS、HSTS 与安全头、TLS 1.2/1.3 实测：`HTTPS_E2E_PASS` | 公共 CA 证书与生产域名（当前为自签名，curl 用 `-k`） |
| PG 主从/归档 | ⚠️ 未改现有 Windows PG（需授权）。已提供隔离演练 runbook `docs/PG_HA_RUNBOOK.md` | 变更窗口授权后按 runbook 执行 |
| 渗透测试 / SOC2 / DPA | ⚠️ 已出内部自评与证据包 `docs/SECURITY_ASSESSMENT.md`（SOC2 控制映射 + 渗透 scope 清单） | 第三方渗透测试、SOC2 审计、法务 DPA |
| T17 完整压测 | ✅ 本地真实栈跑完冷/热启动 ×5 + 1/2/4 空间并发，状态已恢复；见下方数据 | 专用压测环境（可选，用于更大规模与生产规格） |

## T17 压测实测数据

`scripts/load_test.py`，4 空间、5 轮、空闲 3s：

| 场景 | 样本 | 平均 | 最小 | 最大 |
|---|---|---|---|---|
| 冷启动 | 20 | 1.93s | 1.48s | 2.30s |
| 热启动 | 20 | 1.97s | 1.48s | 2.24s |

并发启动总耗时：1 空间 **1.50s**，2 空间 **2.98s**，4 空间 **4.58s**。

压测后 4 个空间 `desired_state=observed_state=running`，4 个运行时容器在跑，health 200。

## 复跑命令

```powershell
.\scripts\oidc-e2e.ps1        # mock IdP + 隔离 API 的 OIDC 端到端
.\scripts\https-e2e.ps1       # 生产 nginx 配置的 TLS/HSTS 端到端
$env:HARNESS_ADMIN_PASSWORD='<admin password>'
.\.venv\Scripts\python.exe .\scripts\load_test.py
```
