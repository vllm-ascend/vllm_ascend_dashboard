#!/bin/bash
# Install or manage recurring MySQL backups.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BACKUP_SCRIPT="$SCRIPT_DIR/backup_db.sh"
LOG_FILE="/var/log/dashboard_backup.log"
CRON_MARKER="# vLLM Dashboard - auto MySQL backup"
FREQUENCY="--hourly"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --hourly) FREQUENCY="--hourly"; shift ;;
        --daily) FREQUENCY="--daily"; shift ;;
        --remove) FREQUENCY="--remove"; shift ;;
        --status) FREQUENCY="--status"; shift ;;
        *) echo "Unknown argument: $1" >&2; exit 2 ;;
    esac
done

if [[ "$FREQUENCY" == "--status" ]]; then
    echo "=== Current cron job ==="
    crontab -l 2>/dev/null | grep -A1 "$CRON_MARKER" || echo "(not installed)"
    echo
    echo "=== Recent MySQL backups ==="
    find "$PROJECT_ROOT/backups" -maxdepth 1 -type f -name 'vllm_dashboard_*.sql' \
        -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -5 | cut -d' ' -f2- || true
    exit 0
fi

if [[ "$FREQUENCY" == "--remove" ]]; then
    (crontab -l 2>/dev/null | grep -vF "$CRON_MARKER" | grep -vF "$BACKUP_SCRIPT" || true) | crontab -
    echo "MySQL backup cron removed"
    exit 0
fi

[[ -x "$BACKUP_SCRIPT" ]] || { echo "Backup script is not executable: $BACKUP_SCRIPT" >&2; exit 1; }
touch "$LOG_FILE" 2>/dev/null || true

if [[ "$FREQUENCY" == "--daily" ]]; then
    CRON_LINE="0 2 * * * $BACKUP_SCRIPT --silent >> $LOG_FILE 2>&1"
    LABEL="daily at 02:00"
else
    CRON_LINE="0 * * * * $BACKUP_SCRIPT --silent >> $LOG_FILE 2>&1"
    LABEL="hourly"
fi

(crontab -l 2>/dev/null | grep -vF "$CRON_MARKER" | grep -vF "$BACKUP_SCRIPT" || true; \
 echo "$CRON_MARKER"; echo "$CRON_LINE") | crontab -

echo "MySQL backup cron installed: $LABEL"
echo "Script: $BACKUP_SCRIPT"
echo "Log: $LOG_FILE"
