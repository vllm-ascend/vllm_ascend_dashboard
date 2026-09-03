# 生产环境部署规范

> **本规范为强制执行标准，所有生产环境部署操作必须严格遵守。**
> 适用对象：人工部署、AI Agent 部署、CI/CD 自动化部署。
> 最后更新：2026-07-15

---

## 1. 红线规则（不可违反）

| 编号 | 规则 | 违反后果 |
|------|------|----------|
| R-01 | **禁止在未备份数据库的情况下执行任何部署/升级操作** | 数据丢失不可恢复 |
| R-02 | **禁止在生产环境运行 `init_db.py`**；只能使用 `operations/production/migrate.sh` | `init_db.py` 是本地初始化工具，可能创建默认用户 |
| R-03 | **禁止直接删除数据库文件**（删除 MySQL 数据卷） | 数据立即丢失 |
| R-04 | **禁止直接修改数据库表结构**（必须通过迁移脚本） | 数据不一致 |
| R-05 | **禁止在未验证备份完整性的情况下继续部署** | 备份可能无效 |
| R-06 | **禁止部署后不验证用户数和服务状态** | 问题无法及时发现 |
| R-07 | **禁止绕过 `deploy.sh` 脚本直接 `git pull && docker compose restart`** | 无备份无验证无回滚 |

---

## 2. 标准部署流程

### 唯一正确的部署方式

```bash
bash operations/production/deploy.sh
```

该脚本自动执行以下 9 个步骤，任何一步失败都会中止或自动回滚：

```
┌─────────────────────────────────────────────────┐
│  Step 1  创建并验证 MySQL 备份                    │
│    └─ --fast 仅检查最近的已验证备份                │
│                                                  │
│  Step 2  记录用户/表数、Git commit 和镜像          │
│    └─ 失败 → 中止部署                              │
│                                                  │
│  Step 3  拉取 upstream/main（可 --no-pull）        │
│  Step 4  拉取不可变镜像（可 --no-pull）             │
│  Step 5  执行 MySQL migration（--fast 跳过）        │
│  Step 6  更新 Docker Compose 服务                  │
│    └─ --fast 只更新 backend/frontend/scheduler/collector │
│                                                  │
│  Step 7  健康检查                                  │
│  Step 8  admin 登录、用户数和表数校验              │
│    └─ 失败 → 自动回滚                              │
│  Step 9  输出部署状态和备份路径                    │
└─────────────────────────────────────────────────┘
```

### 部署选项

```bash
# 标准部署（拉取代码 + 部署）
bash operations/production/deploy.sh

# 不拉取代码，仅重新部署当前版本
bash operations/production/deploy.sh --no-pull

# 快速代码部署：复用最近一次已验证备份，不重新导出数据库，
# 跳过迁移，仅重启 backend/frontend/scheduler/collector
bash operations/production/deploy.sh --fast --no-pull

# 快速部署并拉取 upstream/main 和新镜像
bash operations/production/deploy.sh --fast

# 一键回滚到最近一次备份
bash operations/production/deploy.sh --rollback
```

### 快速部署的边界

`--fast` 不是无备份部署。脚本会执行 `backup.sh --check-latest`，要求备份目录中存在
最近 `DASHBOARD_FAST_BACKUP_MAX_AGE_HOURS`（默认 24 小时）内的已恢复验证备份，并重新校验
备份文件的 SHA-256、用户数和表数。这样可以避免每次代码发布都执行耗时的全量 `mysqldump`。

快速模式只适用于应用代码或镜像变更：

- 跳过 MySQL migration；拉取代码时检测到 `database/`、持久化模型或迁移脚本变化会拒绝继续。
- 不重启 MySQL、LiteLLM，只更新四个业务容器。
- 失败回滚只恢复上一版应用镜像，不恢复数据库，避免用旧备份覆盖当天数据。
- 需要数据库结构变更、配置数据迁移或重要版本升级时，必须使用标准模式，让脚本创建并验证新备份。

若镜像已经在生产机上构建完成，使用 `--fast --no-pull` 可同时跳过远程镜像拉取；否则使用
`--fast`，脚本会正常拉取不可变镜像标签。

---

## 3. 手动备份命令

部署脚本已内置备份，如需单独执行备份：

```bash
# 标准备份（输出详细信息）
bash operations/production/backup.sh

# 静默备份（cron 定时任务用）
bash operations/production/backup.sh --silent

# 仅检查最近一次已验证备份（快速部署会自动执行）
bash operations/production/backup.sh --check-latest

# 自定义保留天数（默认 30 天）
bash operations/production/backup.sh --retention 7
```

备份脚本执行以下操作：
1. 使用 `mysqldump --single-transaction` 在线安全备份（不锁库）
2. 使用 `--verify-restore` 时，将备份恢复到隔离数据库并校验用户数、表数及 SHA-256
3. 统计用户数、数据表数
4. 自动清理超过保留期的旧备份
5. 输出备份文件路径

---

## 4. 定时自动备份

已配置 cron 定时任务，每小时自动备份：

```cron
# vLLM Dashboard - 每小时数据库备份
0 * * * * /root/vllm_ascend_dashboard/operations/production/backup.sh --silent >> /var/log/dashboard_backup.log 2>&1
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

`deploy.sh` 在以下情况会自动回滚：
- 数据库迁移后用户数减少
- 服务重启后 30 秒内未响应
- 部署后验证用户数少于部署前

### 手动回滚

```bash
# 方式一：使用部署脚本回滚
bash operations/production/deploy.sh --rollback

# 方式二：手动恢复
LATEST=$(ls -t /root/vllm_ascend_dashboard/backups/dashboard_*.db | head -1)
systemctl stop dashboard-backend
cp "$LATEST" MySQL 数据由 Docker `mysql_data` volume 管理，不直接操作宿主机文件
systemctl start dashboard-backend

# 方式三：Git 代码回滚 + 数据库恢复
cd /root/vllm_ascend_dashboard
git checkout <上一个稳定commit>
bash operations/production/deploy.sh --no-pull
```

---

## 6. 部署检查清单

每次部署完成后，必须逐项确认：

```
□ 标准模式：数据库新备份已创建；快速模式：最近已验证备份在有效期内
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
| 数据库路径 | `MySQL 数据由 Docker `mysql_data` volume 管理，不直接操作宿主机文件` |
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
bash operations/production/deploy.sh


# ❌ 错误：直接运行 init_db.py（生产环境会被拒绝）
python database/bootstrap.py

# ✅ 正确：使用唯一生产迁移入口（不碰用户）
bash operations/production/migrate.sh


# ❌ 错误：直接删除数据库文件
# 禁止删除 MySQL 数据卷；使用受控恢复流程

# ✅ 正确：先备份再操作
bash operations/production/backup.sh


# ❌ 错误：手动修改数据库表结构
通过 database/migrations/ 执行对应 MySQL 迁移

# ✅ 正确：通过迁移脚本修改
# 新的 schema 变更只能加入 database/migrations/ 调用的显式迁移模块
```




