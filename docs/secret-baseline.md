# Secret 基线

> Phase 0 Step 0.0 产出。盘点所有秘密及其存储位置、分发方式和恢复方法。

## 秘密清单

### 数据库凭据

| 凭据 | 存储位置 | 使用者 | 权限范围 | 轮换方法 |
|------|---------|--------|---------|---------|
| `MYSQL_ROOT_PASSWORD` | `.env.production` | MySQL root | ALL | 修改后重启 MySQL |
| `CONTROL_DB_PASSWORD` | `.env.production` | control_svc | control_db: ALL | 修改后重启 backend |
| `COLLECTOR_DB_PASSWORD` | `.env.production` | collector_svc | collection_db: SELECT,INSERT,UPDATE | 修改后重启 collector |
| `SCHEDULER_DB_PASSWORD` | `.env.production` | scheduler_svc | collection_db: SELECT,INSERT,UPDATE | 修改后重启 scheduler |
| `QUERY_DB_PASSWORD` | `.env.production` | query_svc | collection_db: SELECT | 修改后重启 query |
| `MYSQL_PASSWORD` | `.env.production` | vllm_ascend | vllm_dashboard: ALL (legacy) | 修改后重启各服务 |

### 应用凭据

| 凭据 | 用途 | 存储位置 | 泄露影响 |
|------|------|---------|---------|
| `GITHUB_TOKEN` | GitHub API 访问 | `.env.production` | 可读取 vllm-ascend 仓库 |
| `JWT_SECRET` | API Token 签名 | `.env.production` | 可伪造任意用户 Token |
| `LITELLM_MASTER_KEY` | LLM 网关管理 | `.env.production` | 可修改 LLM 配置 |

### SSH 密钥

| 位置 | 类型 | 用途 |
|------|------|------|
| `~/.ssh/id_rsa` (Windows) | RSA 私钥 | 跳板机免密登录 |
| `~/.ssh/id_rsa` (跳板机) | RSA 私钥 | 生产服务器免密登录（未配置） |
| `/root/.ssh/authorized_keys` (生产) | 公钥 | 允许跳板机和 Windows 登录 |

### 其他

| 项目 | 位置 |
|------|------|
| 生产密码 | openlab@123（SSH 备用） |
| 跳板机 | 123.57.0.174，密钥登录 |
| 看板域名 | http://123.57.0.174 |

## 分发规则

```
Control API → CONTROL_DB_PASSWORD
Collector   → COLLECTOR_DB_PASSWORD + GITHUB_TOKEN + JWT_SECRET
Scheduler   → SCHEDULER_DB_PASSWORD + GITHUB_TOKEN + JWT_SECRET
Query       → QUERY_DB_PASSWORD
```

## 待改进

- [ ] `.env.production` 明文存储，无加密
- [ ] 无凭据轮换机制
- [ ] 备份中包含明文密码（SQL dump 含 GTID_PURGED 等元数据）
- [ ] JWT_SECRET 和 GITHUB_TOKEN 未定期轮换
- [ ] 生产 SSH 密码登录应改为仅密钥登录
