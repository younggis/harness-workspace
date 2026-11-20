# 租户容器资源配额 — 产品方案与实施说明

版本：v1.0（2026-11-20） · 范围：CPU / 内存 / PIDS（本地 Docker 原生支持） · 不含 GPU

## 1. 目标与范围

管理员在新建/修改租户时，可以直接声明该租户工作空间的容器资源规格与运行态总量上限；分配空间时继承租户规格（可显式覆盖），空间启动时受总量配额约束。worker 用空间实际资源创建容器。

本轮不做 GPU：当前 Windows + Docker Desktop 无 NVIDIA Container Toolkit，且容器为 `cap_drop=ALL`/只读根/非 root，GPU 直通需额外宿主能力与安全评审。CPU/内存/PIDS 是 Docker 原生支持的 `nano_cpus` / `mem_limit` / `pids_limit`，可直接落地。

## 2. 分层模型

```
平台硬上限 (limits.py，代码常量，防租户声明超过宿主机)
   └─ 租户资源策略 (tenants)：单空间规格 + 运行态总量上限
        └─ 空间资源 (workspaces)：继承租户规格，可显式覆盖
             └─ 模板 (templates)：仅提供镜像/版本锁定；资源字段作为兜底
                  └─ DockerRuntimeDriver: nano_cpus / mem_limit / pids_limit
```

**为什么仍保留模板资源字段**：模板版本不可变、用于镜像与 dsh 版本锁定和回滚；资源字段保留作向后兼容兜底（老空间 `workspaces.*_resource IS NULL` 时用模板值），不改变现有升级路径。

## 3. 数据模型

### tenants 新增 6 列
| 字段 | 默认 | 含义 |
|---|---|---|
| `cpu_per_space` | 1 | 单空间默认/上限 CPU 核数 |
| `memory_per_space_bytes` | 1 GiB | 单空间默认/上限内存 |
| `pids_per_space` | 256 | 单空间默认/上限进程数 |
| `max_total_cpu` | 4 | 运行态 CPU 总量上限 |
| `max_total_memory_bytes` | 4 GiB | 运行态内存总量上限 |
| `max_total_pids` | 1024 | 运行态 PIDS 总量上限 |

### workspaces 新增 3 列（nullable）
| 字段 | 含义 |
|---|---|
| `cpu` | 空间实际 CPU；NULL = 继承模板（兼容老数据） |
| `memory_bytes` | 空间实际内存；NULL = 继承模板 |
| `pids_limit` | 空间实际 PIDS；NULL = 继承模板 |

## 4. 平台硬上限（limits.py）

| 项 | 最小 | 单空间上限 | 总量上限 |
|---|---|---|---|
| CPU | 1 | 32 核 | 256 核 |
| 内存 | 256 MiB | 64 GiB | 512 GiB |
| PIDS | 64 | 4096 | 65536 |

租户声明超出硬上限 → 409 `CONFLICT`。

## 5. 校验规则

1. **租户创建/修改**：`cpu_per_space ≤ max_total_cpu`、内存与 pids 同理；各字段不得超过平台硬上限。
2. **空间分配**：显式资源不得超过租户 `*_per_space`（租户规格即该租户上限）；未指定则取租户 `*_per_space`。
3. **空间启动**：`Σ运行中空间资源 + 本空间资源 ≤ 租户 max_total_*`（与现有 `max_running` 配额并存）。
4. **修改租户资源**：不立即杀掉已在运行的空间；新配额在下次 start/rebuild 生效，并对账自愈。

## 6. API 变更

- `POST /api/admin/tenants`、`PATCH /api/admin/tenants/{tid}`：新增 6 个资源字段。
- `GET /api/admin/tenants`：列表返回资源字段。
- `POST /api/admin/tenants/{tid}/workspaces`：新增可选 `cpu` / `memory_bytes` / `pids_limit`。
- `GET /api/workspaces`、`GET /api/admin/tenants/{tid}/workspaces`：返回空间实际资源。
- worker `_spec_for`：优先 `workspace.cpu/memory_bytes/pids_limit`，NULL 时回退模板。

## 7. 前端变更

- 管理页「新建租户」对话框：CPU 核数、内存(GB)、PIDS，以及三项总量上限。
- 管理页「工作空间」页签：分配时可选 CPU/内存/PIDS；列表展示实际资源。
- 「我的工作空间」卡片：展示 CPU / 内存 / PIDS。

## 8. 迁移与兼容

- 迁移 `0007_tenant_resources`：tenants 加 6 列（NOT NULL + 默认值），workspaces 加 3 列（nullable）。
- 现有租户回填为默认规格（1 核 / 1 GiB / 256 pids，总量 4 核 / 4 GiB / 1024），与现状一致。
- 现有空间资源字段留 NULL，worker 回退模板，行为不变。

## 9. 测试与验收

- 离线：租户资源校验、继承、覆盖、总量拒绝、worker spec 回退。
- 真实栈：迁移后建租户设资源 → 分配空间 → 启动 → `docker inspect` 验证 nano_cpus/mem_limit/pids_limit。
- 文档：`verification.md` 追加章节。

## 10. 后续（未包含）

GPU：需 NVIDIA Container Toolkit、`device_requests` 驱动支持、隔离与审计策略，单独评审后实施。
