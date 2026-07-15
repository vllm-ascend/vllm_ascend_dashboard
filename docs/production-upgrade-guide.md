# 生产环境部署规范

> **本规范为强制执行标准，所有生产环境部署操作必须严格遵守。**
> 适用对象：人工部署、AI Agent 部署、CI/CD 自动化部署。
> 最后更新：2026-07-15

---

## 1. 红线规则（不可违反）

| 编号 | 规则 | 违反后果 |
|------|------|----------|
| R-01 | **禁止在未备份数据库的情况下执行任何部署/升级操作** | 数据丢失不可恢复 |
| R-02 | **禁止在生产环境运行 `init_db.py` 时不加 `--no-users` 参数** | 全部用户账号被重置 |
| R-03 | **禁止直接删除数据库文件**（`rm dashboard.db`） | 数据立即丢失 |
| R-04 | **禁止直接修改数据库表结构**（必须通过迁移脚本） | 数据不一致 |
| R-05 | **禁止在未验证备份完整性的情况下继续部署** | 备份可能无效 |
| R-06 | **禁止部署后不验证用户数和服务状态** | 问题无法及时发现 |
| R-07 | **禁止绕过 `deploy_prod.sh` 脚本直接 `git pull && systemctl restart`** | 无备份无验证无回滚 |

---

## 2. 标准部署流程

### 唯一正确的部署方式

```bash
bash scripts/deploy_prod.sh
```

该脚本自动执行以下 8 个步骤，任何一步失败都会中止或自动回滚：

```
┌─────────────────────────────────────────────────┐
│  Step 1  备份数据库                              │
│    └─ 失败 → 中止部署                            │
│                                                  │
│  Step 2  验证备份                                │
│    ├─ 完整性校验（PRAGMA integrity_check）        │
│    ├─ 用户数 > 0                                 │
│    └─ 失败 → 中止部署                            │
│                                                  │
│  Step 3  记录部署前状态                           │
│    ├─ 用户数、数据表数                            │
│    ├─ Git commit                                 │
│    └─ 用户列表（打印确认）                        │
│                                                  │
│  Step 4  拉取最新代码                             │
│    └─ 失败 → 中止部署                            │
│                                                  │
│  Step 5  更新后端依赖（uv sync）                   │
│    └─ 失败 → 中止部署                            │
│                                                  │
│  Step 6  数据库迁移                               │
│    ├─ 使用 init_db.py --no-users（不重置用户）     │
│    └─ 迁移后用户数减少 → 自动回滚                  │
│                                                  │
│  Step 7  重启服务                                 │
│    ├─ systemctl restart dashboard-backend        │
│    └─ 30秒内未响应 → 自动回滚                      │
│                                                  │
│  Step 8  部署后验证                               │
│    ├─ 服务状态 running                            │
│    ├─ 用户数 >= 部署前（减少 → 自动回滚）           │
│    ├─ API 健康检查                                │
│    ├─ 登录功能验证                                │
│    └─ 用户列表确认（打印所有用户）                  │
└─────────────────────────────────────────────────┘
```

### 部署选项

```bash
# 标准部署（拉取代码 + 部署）
bash scripts/deploy_prod.sh

# 不拉取代码，仅重新部署当前版本
bash scripts/deploy_prod.sh --no-pull

# 一键回滚到最近一次备份
bash scripts/deploy_prod.sh --rollback
```

---

## 3. 手动备份命令

部署脚本已内置备份，如需单独执行备份：

```bash
# 标准备份（输出详细信息）
bash scripts/backup_db.sh

# 静默备份（cron 定时任务用）
bash scripts/backup_db.sh --silent

# 自定义保留天数（默认 30 天）
bash scripts/backup_db.sh --retention 7
```

备份脚本执行以下操作：
1. 使用 `sqlite3 .backup` 在线安全备份（不锁库）
2. 完整性校验（`PRAGMA integrity_check`）
3. 统计用户数、数据表数
4. 自动清理超过保留期的旧备份
5. 输出备份文件路径

---

## 4. 定时自动备份

已配置 cron 定时任务，每小时自动备份：

```cron
# vLLM Dashboard - 每小时数据库备份
0 * * * * /root/vllm_ascend_dashboard/scripts/backup_db.sh --silent >> /var/log/dashboard_backup.log 2>&1
```

- **备份频率**：每小时整点
- **保留期限**：30 天
- **备份位置**：`/root/vllm_ascend_dashboard/backups/`
- **日志位置**：`/var/log/dashboard_backup.log`

查看备份历史：

```bash
ls -lh /root/vllm_ascend_dashboard/backups/
tail -50 /var/log/dashboard_backup.log
```

---

## 5. 回滚方案

### 自动回滚

`deploy_prod.sh` 在以下情况会自动回滚：
- 数据库迁移后用户数减少
- 服务重启后 30 秒内未响应
- 部署后验证用户数少于部署前

### 手动回滚

```bash
# 方式一：使用部署脚本回滚
bash scripts/deploy_prod.sh --rollback

# 方式二：手动恢复
LATEST=$(ls -t /root/vllm_ascend_dashboard/backups/dashboard_*.db | head -1)
systemctl stop dashboard-backend
cp "$LATEST" /root/vllm_ascend_dashboard/backend/data/dashboard.db
systemctl start dashboard-backend

# 方式三：Git 代码回滚 + 数据库恢复
cd /root/vllm_ascend_dashboard
git checkout <上一个稳定commit>
bash scripts/deploy_prod.sh --no-pull
```

---

## 6. 部署检查清单

每次部署完成后，必须逐项确认：

```
□ 数据库备份已创建（backups/ 目录有新文件）
□ 备份完整性校验通过
□ 备份中用户数 > 0
□ 后端服务状态为 active (running)
□ 部署后用户数 >= 部署前用户数
□ API 健康检查通过（curl /api/v1/health）
□ admin 账号可正常登录
□ 所有用户账号完好（打印用户列表确认）
□ Nginx 正常响应（curl http://123.57.0.174/）
□ 前端页面可正常访问
```

---

## 7. 服务器信息

| 项目 | 值 |
|------|-----|
| 目标服务器 | 123.57.0.174（阿里云 ECS） |
| SSH 登录 | `ssh -i ~/.ssh/id_rsa root@123.57.0.174`（直连，无需跳板机） |
| 项目路径 | `/root/vllm_ascend_dashboard/` |
| 后端服务 | `systemctl status dashboard-backend` |
| Nginx 配置 | `/etc/nginx/sites-available/dashboard` |
| 数据库路径 | `/root/vllm_ascend_dashboard/backend/data/dashboard.db` |
| 环境配置 | `/root/vllm_ascend_dashboard/.env` |
| 备份目录 | `/root/vllm_ascend_dashboard/backups/` |

---

## 8. 历史教训

| 日期 | 事件 | 原因 | 教训 |
|------|------|------|------|
| 2026-07-14 | 数据库重建导致全部用户账号丢失 | 部署时未备份，直接运行 `init_db.py` 重置了数据库 | 促成本规范的制定和 `deploy_prod.sh` 的开发 |

---

## 9. 错误操作对照表

```bash
# ❌ 错误：直接拉代码重启（无备份无验证无回滚）
git pull && systemctl restart dashboard-backend

# ✅ 正确：使用部署脚本
bash scripts/deploy_prod.sh


# ❌ 错误：直接运行 init_db.py（会重置所有用户）
python scripts/init_db.py

# ✅ 正确：加 --no-users 参数（仅建表/升级，不碰用户）
python scripts/init_db.py --no-users


# ❌ 错误：直接删除数据库文件
rm backend/data/dashboard.db

# ✅ 正确：先备份再操作
bash scripts/backup_db.sh


# ❌ 错误：手动修改数据库表结构
sqlite3 dashboard.db "ALTER TABLE users DROP COLUMN ..."

# ✅ 正确：通过迁移脚本修改
# 创建 backend/scripts/upgrade_vX.Y.Z.py 并通过 init_db.py --no-users 执行
```
