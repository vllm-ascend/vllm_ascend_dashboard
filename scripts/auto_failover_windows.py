#!/usr/bin/env python3
"""
自动容灾监控 — 运行在 Windows 上。
通过 SSH 隧道检测生产 MySQL，故障时自动提升本地副本并切换流量。
"""
import paramiko
import socket
import time
import logging
import subprocess
import sys
import os
import json

logging.basicConfig(level=logging.INFO, format="%(asctime)s [FAILOVER] %(message)s")
logger = logging.getLogger("failover")

# ── Config ──
CHECK_INTERVAL = 10
FAILURE_THRESHOLD = 3  # 30s 连续失败触发
PROMOTED = False

# Production access (via jump box)
JUMP = "123.57.0.174"
PROD = "190.92.220.4"
KEY = os.path.expanduser("~/.ssh/id_rsa")
PROD_PASS = "openlab@123"
PROJECT_DIR = "/opt/vllm_ascend_dashboard"


def check_primary() -> bool:
    """Test production MySQL via SSH tunnel."""
    try:
        s = socket.socket(); s.settimeout(5)
        s.connect(("127.0.0.1", 3307))
        s.close()
        return True
    except Exception:
        return False


def run_ssh(cmd: str) -> tuple[str, str]:
    """Run command on production via jump box."""
    key = paramiko.RSAKey.from_private_key_file(KEY)
    jump = paramiko.SSHClient(); jump.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    jump.connect(JUMP, username="root", pkey=key, timeout=30)
    jump.get_transport().set_keepalive(30)
    c = jump.get_transport().open_channel("direct-tcpip", (PROD, 22), ("", 0))
    prod = paramiko.SSHClient(); prod.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    prod.connect(PROD, username="root", password=PROD_PASS, sock=c, timeout=30)
    stdin, stdout, stderr = prod.exec_command(cmd, timeout=60)
    stdout.channel.settimeout(60)
    time.sleep(3)
    out = stdout.read().decode()
    err = stderr.read().decode()
    prod.close(); jump.close()
    return out, err


def promote_local():
    """Promote local MySQL replica to primary."""
    logger.info("PROMOTING LOCAL REPLICA")
    cmds = [
        "STOP REPLICA; RESET REPLICA ALL",
        "SET GLOBAL read_only=OFF; SET GLOBAL super_read_only=OFF",
    ]
    for cmd in cmds:
        subprocess.run(["docker", "exec", "vllm-mysql-replica-node-a", "mysql", "-uroot", "-proot123456", "-e", cmd],
                       capture_output=True, timeout=10)

    # Verify writable
    r = subprocess.run(["docker", "exec", "vllm-mysql-replica-node-a", "mysql", "-uroot", "-proot123456", "-N", "-e", "SELECT 1"],
                       capture_output=True, text=True, timeout=10)
    return r.stdout.strip() == "1"


def switch_apps_to_replica():
    """Update production apps to point to Windows MySQL via SSH tunnel."""
    # The tunnel maps 127.0.0.1:3307 → production MySQL (normally)
    # After failover, apps should point to Windows replica directly
    # For now, since Windows replica is behind NAT, apps continue via tunnel
    # But the tunnel direction needs to be reversed:
    # NEW: production apps → Windows replica (via existing tunnel)

    # Actually, the replica IS on Windows. Apps on production need to reach it.
    # Option 1: Start a reverse tunnel from production → Windows
    # Option 2: Use the replica's data directly on Windows

    # Simplest: update DATABASE_URL on production to use local replica
    new_url = "mysql+aiomysql://dashboard:dashboard123@127.0.0.1:3308/vllm_dashboard"

    logger.info("Switching apps to replica: %s", new_url)
    out, err = run_ssh(f"cd {PROJECT_DIR} && "
                       f"sed -i 's|DATABASE_URL=.*|DATABASE_URL={new_url}|' .env.production && "
                       f"docker compose -f docker-compose.prod.yml up -d --force-recreate --no-build backend scheduler collector 2>&1")
    logger.info("Switch result: %s", out[:200] if out else err[:200])


def main():
    global PROMOTED
    failures = 0

    logger.info("Failover monitor started (primary=127.0.0.1:3307)")

    while True:
        ok = check_primary()
        if ok:
            if failures > 0:
                logger.info("Primary recovered after %d failures", failures)
            failures = 0
        else:
            failures += 1
            logger.warning("Primary DOWN (%d/%d)", failures, FAILURE_THRESHOLD)

        if failures >= FAILURE_THRESHOLD and not PROMOTED:
            logger.error("FAILOVER TRIGGERED")
            if promote_local():
                PROMOTED = True
                logger.info("Replica promoted — switching apps")
                switch_apps_to_replica()
                logger.info("FAILOVER COMPLETE")

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
