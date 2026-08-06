#!/bin/bash
# 健康检查脚本
set -euo pipefail

ok() { echo "[OK] $1"; }
warn() { echo "[WARN] $1"; }

echo "=== Health Check $(date) ==="

# Containers
for c in vllm-dashboard-mysql vllm-dashboard-backend vllm-dashboard-frontend vllm-dashboard-scheduler vllm-dashboard-collector; do
    status=$(docker inspect "$c" --format '{{.State.Health.Status}}' 2>/dev/null || echo "missing")
    [[ "$status" == "healthy" ]] && ok "$c" || warn "$c: $status"
done

# Disk
pct=$(df / | awk 'NR==2{print $5}' | tr -d '%')
[[ "$pct" -lt 85 ]] && ok "disk: ${pct}%" || warn "disk: ${pct}%"

# Backup
count=$(find /opt/vllm_ascend_dashboard/backups -name "*.sql" -mtime -1 2>/dev/null | wc -l)
[[ "$count" -gt 0 ]] && ok "backup: $count in 24h" || warn "backup: NONE"

# API
curl -fsS --connect-timeout 5 http://127.0.0.1:3000/health >/dev/null 2>&1 && ok "api" || warn "api: DOWN"

echo "Done"
