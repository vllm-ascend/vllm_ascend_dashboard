#!/bin/bash
set -e

echo "Starting vLLM Ascend Dashboard backend..."

# Fix permissions on mounted volumes before dropping privileges.
chown -R appuser:appuser /app/data /app/logs
chmod -R 755 /app/data /app/logs
# A single-file bind mount must remain writable by the application user.
[ -f /app/litellm_config.yaml ] && chmod 666 /app/litellm_config.yaml

echo "Permissions fixed, starting application..."

# Allow docker-compose to select another process role via command.
if [[ -n "${1:-}" ]]; then
    echo "Starting with command: $*"
    exec su appuser -c "cd /app && PYTHONPATH=/app exec $*"
else
    exec su appuser -c "cd /app && PYTHONPATH=/app /opt/venv/bin/uvicorn api.main:app --host 0.0.0.0 --port 8000"
fi
