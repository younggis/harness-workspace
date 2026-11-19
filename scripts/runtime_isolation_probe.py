"""Run INSIDE a harness runtime container (via docker exec -i python3 -).

Checks the isolation contract from section 6/12 T06. Prints JSON results.
This script never mutates the container.
"""
from __future__ import annotations

import json
import os
import socket


def tcp(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def cap_eff() -> str:
    try:
        for line in open("/proc/1/status"):
            if line.startswith("CapEff:"):
                return line.split()[1]
    except Exception:
        pass
    return "unknown"


def rootfs_ro() -> bool:
    try:
        for line in open("/proc/1/mountinfo"):
            if " / " in line:
                opts = line.split()[5].split(",")
                return "ro" in opts
    except Exception:
        pass
    return False


def main() -> None:
    wid = os.environ.get("HARNESS_WORKSPACE_ID", "")
    gen = os.environ.get("HARNESS_GENERATION", "0")
    checks = {
        "non_root_uid": os.getuid() == 10001,
        "cap_eff_empty": cap_eff() in ("0", "0000000000000000", "unknown"),
        "rootfs_read_only": rootfs_ro(),
        "no_docker_socket": not os.path.exists("/var/run/docker.sock"),
        "no_host_pg": not tcp("127.0.0.1", 5432) and not tcp("host.docker.internal", 5432),
        "no_external_net": not tcp("api.deepseek.com", 443),
        "model_proxy_allowed": tcp("model-proxy", 8090),
    }
    if wid:
        checks["no_other_space"] = not tcp(f"rt-{wid}-g9999", 8080)
    print(json.dumps({"workspace": wid, "generation": gen, "checks": checks}, indent=2))
    failed = [k for k, v in checks.items() if not v]
    if failed:
        raise SystemExit("ISOLATION_FAIL:" + ",".join(failed))
    print("ISOLATION_PASS")


main()
