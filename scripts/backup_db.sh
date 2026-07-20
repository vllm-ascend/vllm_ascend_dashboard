#!/bin/bash
# Online MySQL backup for the production Docker deployment.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BACKUP_DIR="${DASHBOARD_BACKUP_DIR:-$PROJECT_ROOT/backups}"
MYSQL_CONTAINER="${DASHBOARD_MYSQL_CONTAINER:-vllm-dashboard-mysql}"
RETENTION_DAYS=30
SILENT=false
VERIFY_RESTORE=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --silent) SILENT=true; shift ;;
        --verify-restore) VERIFY_RESTORE=true; shift ;;
        --retention) RETENTION_DAYS="${2:?retention days required}"; shift 2 ;;
        *) echo "Unknown argument: $1" >&2; exit 2 ;;
    esac
done

log() { $SILENT || echo "[BACKUP] $1"; }
die() { echo "[ERROR] $1" >&2; exit 1; }
mysql_root() {
    docker exec "$MYSQL_CONTAINER" sh -c \
        'exec mysql -uroot -p"$MYSQL_ROOT_PASSWORD" "$MYSQL_DATABASE" -N -e "$1"' sh "$1"
}

command -v docker >/dev/null 2>&1 || die "docker is not installed"
docker inspect "$MYSQL_CONTAINER" >/dev/null 2>&1 || die "MySQL container is unavailable: $MYSQL_CONTAINER"
[[ "$RETENTION_DAYS" =~ ^[0-9]+$ ]] || die "retention must be a non-negative integer"
database_name="$(docker exec "$MYSQL_CONTAINER" sh -c 'printf %s "$MYSQL_DATABASE"')"
[[ "$database_name" =~ ^[a-zA-Z0-9_]+$ ]] || die "unsafe MySQL database name"

mkdir -p "$BACKUP_DIR"
timestamp="$(date +%Y%m%d_%H%M%S)"
backup_file="$BACKUP_DIR/vllm_dashboard_${timestamp}.sql"
metadata_file="$backup_file.meta"

pre_users="$(mysql_root 'SELECT COUNT(*) FROM users')"
pre_tables="$(mysql_root 'SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = DATABASE()')"
[[ "$pre_users" =~ ^[0-9]+$ ]] && (( pre_users > 0 )) || die "live database user count is invalid: $pre_users"
[[ "$pre_tables" =~ ^[0-9]+$ ]] && (( pre_tables > 0 )) || die "live database table count is invalid: $pre_tables"

log "creating transaction-consistent MySQL dump"
if ! docker exec "$MYSQL_CONTAINER" sh -c \
    'exec mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" --single-transaction --quick --routines --triggers --events --set-gtid-purged=OFF "$1"' sh "$database_name" \
    > "$backup_file"; then
    rm -f "$backup_file"
    die "mysqldump failed"
fi

[[ -s "$backup_file" ]] || die "backup is empty"
grep -q 'CREATE TABLE `users`' "$backup_file" || die "backup does not contain users table"
grep -q 'Dump completed on' "$backup_file" || die "mysqldump completion marker is missing"

backup_users="$pre_users"
backup_tables="$pre_tables"
if $VERIFY_RESTORE; then
    verify_db="vllm_dashboard_verify_${timestamp}"
    [[ "$verify_db" =~ ^[a-zA-Z0-9_]+$ ]] || die "unsafe verification database name"
    cleanup_verify() {
        docker exec "$MYSQL_CONTAINER" sh -c \
            'exec mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -e "DROP DATABASE IF EXISTS \`$1\`"' sh "$verify_db" \
            >/dev/null 2>&1 || true
    }
    trap cleanup_verify EXIT
    docker exec "$MYSQL_CONTAINER" sh -c \
        'exec mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -e "CREATE DATABASE \`$1\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"' sh "$verify_db"
    docker exec -i "$MYSQL_CONTAINER" sh -c \
        'exec mysql -uroot -p"$MYSQL_ROOT_PASSWORD" "$1"' sh "$verify_db" < "$backup_file"
    backup_users="$(docker exec "$MYSQL_CONTAINER" sh -c \
        'exec mysql -uroot -p"$MYSQL_ROOT_PASSWORD" "$1" -N -e "SELECT COUNT(*) FROM users"' sh "$verify_db")"
    backup_tables="$(docker exec "$MYSQL_CONTAINER" sh -c \
        'exec mysql -uroot -p"$MYSQL_ROOT_PASSWORD" "$1" -N -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = DATABASE()"' sh "$verify_db")"
    [[ "$backup_users" = "$pre_users" ]] || die "restore verification user count mismatch: $pre_users -> $backup_users"
    [[ "$backup_tables" = "$pre_tables" ]] || die "restore verification table count mismatch: $pre_tables -> $backup_tables"
    cleanup_verify
    trap - EXIT
fi

checksum="$(sha256sum "$backup_file" | awk '{print $1}')"
git_commit="$(git -C "$PROJECT_ROOT" rev-parse --short HEAD 2>/dev/null || echo unknown)"
{
    echo "created_at=$(date --iso-8601=seconds)"
    echo "git_commit=$git_commit"
    echo "sha256=$checksum"
    echo "users=$backup_users"
    echo "tables=$backup_tables"
    echo "restore_verified=$VERIFY_RESTORE"
} > "$metadata_file"

find "$BACKUP_DIR" -maxdepth 1 -type f \
    \( -name 'vllm_dashboard_*.sql' -o -name 'vllm_dashboard_*.sql.meta' \) \
    -mtime "+$RETENTION_DAYS" -delete

log "backup verified: users=$backup_users tables=$backup_tables sha256=$checksum"
echo "$backup_file"
