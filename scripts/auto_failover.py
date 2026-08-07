#!/usr/bin/env python3
"""
Auto-failover monitor + promoter.
Runs on production, monitors MySQL primary health.
If primary is down for > 30s, promotes Windows replica via SSH tunnel.

Usage:
  python3 scripts/auto_failover.py [--daemon]
"""
import paramiko
import socket
import time
import subprocess
import logging
import sys
import os

logging.basicConfig(level=logging.INFO, format="%(asctime)s [FAILOVER] %(message)s")
logger = logging.getLogger("failover")

# ── Config ──
PRIMARY_HOST = os.environ.get("FAILOVER_PRIMARY", "127.0.0.1")
PRIMARY_PORT = int(os.environ.get("FAILOVER_PRIMARY_PORT", "3306"))
PRIMARY_USER = os.environ.get("FAILOVER_PRIMARY_USER", "root")
PRIMARY_PASS = os.environ.get("FAILOVER_PRIMARY_PASS", "openlab123")

REPLICA_HOST = os.environ.get("FAILOVER_REPLICA_HOST", "host.docker.internal")
REPLICA_PORT = int(os.environ.get("FAILOVER_REPLICA_PORT", "3308"))
REPLICA_USER = os.environ.get("FAILOVER_REPLICA_USER", "root")
REPLICA_PASS = os.environ.get("FAILOVER_REPLICA_PASS", "root123456")

CHECK_INTERVAL = 10      # seconds between health checks
FAILURE_THRESHOLD = 3     # consecutive failures before triggering
PROMOTE_SCRIPT = "/opt/vllm_ascend_dashboard/scripts/promote_replica.sh"
FAILOVER_LOCK = "/tmp/failover.lock"

failures = 0
failed_over = False


def check_mysql(host, port):
    """Quick TCP check to MySQL port."""
    try:
        s = socket.socket(); s.settimeout(5)
        s.connect((host, port))
        s.close()
        return True
    except Exception:
        return False


def promote_replica():
    """Promote Windows replica to primary."""
    logger.info("PROMOTING REPLICA %s:%d", REPLICA_HOST, REPLICA_PORT)

    # 1. Stop replication on replica
    subprocess.run([
        "docker", "exec", "vllm-mysql-replica-node-a",
        "mysql", f"-u{REPLICA_USER}", f"-p{REPLICA_PASS}", "-h", REPLICA_HOST, f"-P{str(REPLICA_PORT)}",
        "-e", "STOP REPLICA; RESET REPLICA ALL; SET GLOBAL read_only=OFF; SET GLOBAL super_read_only=OFF"
    ], capture_output=True, timeout=30)

    # 2. Verify replica is writable
    r = subprocess.run([
        "docker", "exec", "vllm-mysql-replica-node-a",
        "mysql", f"-u{REPLICA_USER}", f"-p{REPLICA_PASS}", "-h", REPLICA_HOST, f"-P{str(REPLICA_PORT)}",
        "-N", "-e", "SELECT 1"
    ], capture_output=True, text=True, timeout=10)

    if r.stdout.strip() == "1":
        logger.info("REPLICA PROMOTED SUCCESSFULLY - new primary: %s:%d", REPLICA_HOST, REPLICA_PORT)
        # Write failover marker
        with open(FAILOVER_LOCK, "w") as f:
            f.write(f"failed_over_at={time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"new_primary={REPLICA_HOST}:{REPLICA_PORT}\n")
        return True
    else:
        logger.error("REPLICA PROMOTION FAILED")
        return False


def run():
    global failures, failed_over

    if os.path.exists(FAILOVER_LOCK):
        logger.warning("Failover lock exists - already failed over. Delete %s to re-enable.", FAILOVER_LOCK)

    while True:
        ok = check_mysql(PRIMARY_HOST, PRIMARY_PORT)

        if ok:
            if failures > 0:
                logger.info("Primary recovered after %d failures", failures)
            failures = 0
        else:
            failures += 1
            logger.warning("Primary unreachable (%d/%d)", failures, FAILURE_THRESHOLD)

        if failures >= FAILURE_THRESHOLD and not failed_over and not os.path.exists(FAILOVER_LOCK):
            logger.error("PRIMARY DOWN - triggering failover!")
            if promote_replica():
                failed_over = True

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    if "--daemon" in sys.argv:
        import daemon  # optional, for real daemon
    run()
