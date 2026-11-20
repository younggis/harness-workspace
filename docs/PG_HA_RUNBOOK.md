# PostgreSQL 主从 / 归档变更 Runbook（待授权）

状态：**未执行**。现有 Windows PostgreSQL 属于用户既有环境，修改 `postgresql.conf` / `pg_hba.conf` 并重启属于系统级变更，需显式授权。本文档提供可直接执行的隔离方案与验证清单。

## 1. 推荐路径：用独立 PG 实例做演练，不碰现有实例

优先在 Docker 中新建一个**独立 PostgreSQL 实例**做 HA/PITR 验证，与既有 PG 完全隔离：

```powershell
docker run -d --name harness-pg-ha-test `
  -e POSTGRES_PASSWORD=<strong> `
  -p 15432:5432 `
  -v harness_pg_ha_data:/var/lib/postgresql/data `
  postgres:12
```

在该实例上完成归档/主从/PITR 全部验证后，再把结论套用到生产变更窗口。

## 2. 归档（WAL archiving）配置

在目标实例的 `postgresql.conf`：

```
wal_level = replica
archive_mode = on
archive_command = 'powershell -NoProfile -Command "Copy-Item %p F:\pg_archive\%f"'
archive_timeout = 300
max_wal_senders = 10
```

验证：

```sql
SELECT name, setting FROM pg_settings WHERE name IN ('wal_level','archive_mode','archive_command');
SELECT pg_switch_wal();
-- 确认 F:\pg_archive 出现新 WAL 文件
```

## 3. 流式复制（备库）

主库 `pg_hba.conf`：

```
host replication repluser 127.0.0.1/32 scram-sha-256
```

主库创建复制角色：

```sql
CREATE ROLE repluser WITH REPLICATION LOGIN PASSWORD '<strong>';
```

备库初始化：

```powershell
pg_basebackup -h 127.0.0.1 -p 15432 -U repluser -D F:\pg_standby -Fp -Xs -R -P
```

备库 `postgresql.auto.conf` 由 `-R` 写入 `primary_conninfo`；启动备库后验证：

```sql
SELECT status, receive_start_lsn, latest_end_lsn FROM pg_stat_wal_receiver;
SELECT pg_is_in_recovery();  -- 备库应为 true
```

## 4. PITR 验证

已有 `scripts/pg-pitr-drill.ps1` 在 `harness_test` schema 上做过演练（`PITR_DRILL_PASS`）。HA 场景下重复：

1. 基础备份：`pg_basebackup` 或 `pg_backup_start/stop`
2. 制造可识别的数据变更并记录时间点
3. 恢复到一个临时目录，`recovery_target_time` 指向变更前
4. 启动并确认数据回到目标时间点

## 5. 切换与回滚

- **计划内切换**：主库 `pg_ctl stop -m fast` → 备库 `pg_ctl promote` → 应用连接串切到新主（本平台通过 `PG_HOST` 切换）
- **回滚**：保留原主库数据目录不删；切换前先 `SELECT pg_current_wal_lsn()` 记录位点，必要时以原主为基础重新搭建复制
- **平台侧**：切换 `PG_HOST` 后重建控制面容器（`docker compose up -d --force-recreate api worker llm`），运行 `health/ready` 与 `docs/verification.md` 的验收清单

## 6. 变更窗口清单（需授权后执行）

- [ ] 维护者确认窗口与回滚负责人
- [ ] 对现有 PG 做完整冷备份并校验
- [ ] 先在隔离 PG 实例完成上述 2–4 全部验证
- [ ] 改配置前记录原始 `postgresql.conf` / `pg_hba.conf` 校验和
- [ ] 变更 → 重启 → 跑验证 SQL → 跑平台 health/ready
- [ ] 保留回滚窗口；确认无异常后再清理旧备份

## 7. 本平台已具备的能力

备份/恢复脚本 `scripts/backup.ps1`、`restore.ps1` 与 PITR 演练 `pg-pitr-drill.ps1` 已落地并真实通过（`BACKUP_OK` / `RESTORE_OK` / `PITR_DRILL_PASS`）。本 runbook 只覆盖宿主 PG 自身的 HA/归档配置。
