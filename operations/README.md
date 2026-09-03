# Operations

Operational commands are separated from deployment declarations.

- `production/`: deployment, backup, restore verification, migration, and health checks.
- `cluster/`: node membership, replica promotion, and failover tooling.
- `development/`: local-only setup and diagnostics.

Run production deployment only through `production/deploy.sh`. It reads
`deploy/compose/production/compose.yml` and the runtime environment file
selected by `DASHBOARD_ENV_FILE` (default:
`/etc/vllm-ascend-dashboard/production.env`). In production, that environment file and
the LiteLLM/MySQL config files must live outside the Git checkout; the paths
are supplied through `DASHBOARD_RUNTIME_ENV_FILE`,
`DASHBOARD_LITELLM_CONFIG_FILE`, and `DASHBOARD_MYSQL_CONFIG_FILE`.

For an application-only release where no schema or data migration is needed,
use `bash operations/production/deploy.sh --fast --no-pull` when the new images
are already present on the host. Fast mode reuses a recent restore-verified
backup, skips migrations, leaves MySQL/LiteLLM running, and rolls back only
application images. Use the standard command for schema changes or major
upgrades; it creates and verifies a fresh backup.

The database volume names are explicit and external. The deployment refuses
to create a missing volume, because doing so could start the service against
an empty database. A one-time configuration migration should be performed
from a protected temporary location on the target host, verified, and then
removed; it must not become an application or repository configuration file.

For the existing installation, the one-time preparation is equivalent to:

```bash
install -d -m 700 /etc/vllm-ascend-dashboard
install -m 600 /opt/vllm_ascend_dashboard/.env.production \
  /etc/vllm-ascend-dashboard/production.env
install -m 600 /opt/vllm_ascend_dashboard/deploy/config/litellm_config.yaml \
  /etc/vllm-ascend-dashboard/litellm_config.yaml
install -m 644 /opt/vllm_ascend_dashboard/deploy/config/mysql.cnf \
  /etc/vllm-ascend-dashboard/mysql.cnf
```

The copied environment file must then be updated with the immutable image
digests and the external paths from `.env.production.example`. The database
is migrated in place through the existing external MySQL volume; no database
dump is copied into the Git checkout. Any temporary conversion script or
plaintext export is deleted after its checksum, row counts, and service
health have been verified.
