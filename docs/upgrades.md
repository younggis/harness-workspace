# 上游 dsh 升级门禁记录

每次升级前运行 `.\scripts\upgrade-check.ps1 -Version <新版本>`：
构建候选镜像 → 校验镜像内 `dsh --version` → 跑契约与离线测试 → 通过才允许注册新模板。

升级完整流程：
1. `.env.local` 设置 `DSH_VERSION=<新版本>`
2. `upgrade-check.ps1 -Version <新版本>`（记录追加到本文件）
3. 用候选镜像启动一个临时空间，运行 `scripts/capture_contracts.py` 与
   `scripts/capture_session_contract.py`，对比 `contracts/upstream/` 差异；
   若适配器依赖的交换/事件/配置形状变了，先改适配器再重跑门禁
4. `POST /api/admin/templates` 注册**新版本**模板（带 `dsh_version`），旧模板保留可回滚
5. 逐空间 rebuild（挂原卷），验证会话与文件恢复

记录（Append only）：
