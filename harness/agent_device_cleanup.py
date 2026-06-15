#!/usr/bin/env python3
import argparse
import os
import signal
import subprocess
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DAEMON_MARKER = str(ROOT / "node_modules" / "agent-device" / "dist" / "src" / "internal" / "daemon.js")


def repo_agent_device_daemons():
    proc = subprocess.run(["ps", "-axo", "pid=,command="], text=True, capture_output=True, check=True)
    current_pid = os.getpid()
    daemons = []
    for line in proc.stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        pid_text, _, command = stripped.partition(" ")
        if not pid_text.isdigit():
            continue
        pid = int(pid_text)
        if pid == current_pid:
            continue
        if DAEMON_MARKER in command:
            daemons.append({"pid": pid, "command": command})
    return daemons


def terminate_repo_agent_device_daemons(grace_seconds=2.0):
    daemons = repo_agent_device_daemons()
    for daemon in daemons:
        try:
            os.kill(daemon["pid"], signal.SIGTERM)
        except ProcessLookupError:
            pass

    deadline = time.time() + grace_seconds
    while time.time() < deadline:
        remaining = repo_agent_device_daemons()
        if not remaining:
            return {"terminated": daemons, "killed": [], "remaining": []}
        time.sleep(0.1)

    remaining = repo_agent_device_daemons()
    killed = []
    for daemon in remaining:
        try:
            os.kill(daemon["pid"], signal.SIGKILL)
            killed.append(daemon)
        except ProcessLookupError:
            pass
    time.sleep(0.1)
    return {
        "terminated": daemons,
        "killed": killed,
        "remaining": repo_agent_device_daemons(),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--list", action="store_true", help="list repo-owned agent-device daemon PIDs without terminating them")
    parser.add_argument("--grace-seconds", type=float, default=2.0)
    args = parser.parse_args()

    if args.list:
        for daemon in repo_agent_device_daemons():
            print(f"{daemon['pid']} {daemon['command']}")
        return

    result = terminate_repo_agent_device_daemons(args.grace_seconds)
    print(
        "agent-device cleanup: "
        f"terminated={len(result['terminated'])} "
        f"killed={len(result['killed'])} "
        f"remaining={len(result['remaining'])}"
    )
    for daemon in result["remaining"]:
        print(f"remaining {daemon['pid']} {daemon['command']}")


if __name__ == "__main__":
    main()
