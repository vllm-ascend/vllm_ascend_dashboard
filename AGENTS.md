# AGENTS.md — AI Agent 操作规范

> 本文件定义 AI Agent（包括 opencode、自动化脚本等）在本项目中的操作红线和规范。
> **所有 Agent 必须严格遵守，违反红线可能导致数据丢失。**

## 生产环境部署红线

### 绝对禁止的操作

1. **禁止直接删除数据库文件**（`rm dashboard.db`）
2. **禁止在生产环境运行 `init_db.py` 时不加 `--no-users` 参数**（会重置所有用户）
3. **禁止在未备份数据库的情况下执行部署/升级操作**
4. **禁止直接修改数据库表结构**（必须通过迁移脚本）
5. **禁止在未验证备份的情况下继续部署**

### 部署前必须执行的步骤

```
1. 备份数据库     → bash scripts/backup_db.sh
2. 验证备份       → 检查完整性校验通过 + 用户数 > 0
3. 记录当前状态   → 用户数、表数、Git commit
```

### 部署后必须执行的步骤

```
1. 验证服务状态   → systemctl is-active dashboard-backend
2. 验证用户数     → 部署后用户数 >= 部署前用户数（减少则自动回滚）
3. 验证 API 健康  → curl http://127.0.0.1:8000/api/v1/health
4. 验证登录功能   → 测试 admin 账号可正常登录
5. 确认用户列表   → 打印所有用户，人工确认无丢失
```

### 正确的部署方式

```bash
# ✅ 正确：使用部署脚本（自动备份+验证+回滚）
bash scripts/deploy_prod.sh

# ❌ 错误：直接拉代码重启（无备份无验证）
git pull && systemctl restart dashboard-backend

# ❌ 错误：直接运行 init_db.py（会重置用户）
python scripts/init_db.py
```

## 数据库操作规范

- **备份命令**: `bash scripts/backup_db.sh`
- **迁移命令**: `python scripts/init_db.py --no-users`（仅建表/升级，不碰用户）
- **回滚命令**: `bash scripts/deploy_prod.sh --rollback`
- **定时备份**: cron 每小时自动执行 `backup_db.sh --silent`
- **备份保留**: 30 天，超出自动清理
- **备份位置**: `/root/vllm_ascend_dashboard/backups/`

## 服务器信息

- **目标服务器**: 123.57.0.174（阿里云 ECS）
- **SSH 登录**: `ssh -i ~/.ssh/id_rsa root@123.57.0.174`（直连，无需跳板机）
- **项目路径**: `/root/vllm_ascend_dashboard/`
- **后端服务**: `systemctl status dashboard-backend`
- **Nginx 配置**: `/etc/nginx/sites-available/dashboard`
- **数据库路径**: `/root/vllm_ascend_dashboard/backend/data/dashboard.db`
- **环境配置**: `/root/vllm_ascend_dashboard/.env`

## 开发环境命令

### 后端
```bash
cd backend
uv sync                    # 安装依赖
uv run pytest              # 运行测试
uv run ruff check .        # 代码检查
uv run mypy .              # 类型检查
uv run uvicorn app.main:app --reload  # 开发服务器
```

### 前端
```bash
cd frontend
pnpm install               # 安装依赖
pnpm dev                   # 开发服务器
pnpm build                 # 构建生产版本
pnpm lint                  # 代码检查
```
