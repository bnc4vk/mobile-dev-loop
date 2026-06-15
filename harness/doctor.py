#!/usr/bin/env python3
import argparse
import json
import os
import platform
import re
import shutil
import subprocess
from pathlib import Path

from local_config import LOCAL_ENV, load_local_env


ROOT = Path(__file__).resolve().parents[1]
LOCAL_NODE = ROOT / "node_modules" / "node" / "bin" / "node"
LOCAL_NODE_BIN = ROOT / "node_modules" / "node" / "bin"


def repo_tool_env():
    env = os.environ.copy()
    if LOCAL_NODE_BIN.exists():
        env["PATH"] = f"{LOCAL_NODE_BIN}{os.pathsep}{env.get('PATH', '')}"
    return env


def run(cmd, cwd=ROOT, timeout=30, env=None):
    try:
        proc = subprocess.run(cmd, cwd=cwd, env=env, text=True, capture_output=True, timeout=timeout)
        return {"cmd": cmd, "ok": proc.returncode == 0, "exitCode": proc.returncode, "stdout": proc.stdout.strip(), "stderr": proc.stderr.strip()}
    except Exception as error:
        return {"cmd": cmd, "ok": False, "error": str(error)}


def semver_tuple(version):
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", version)
    if not match:
        return None
    return tuple(int(part) for part in match.groups())


def check_command(name, command, version_args=None):
    path = shutil.which(command[0])
    result = {"name": name, "path": path, "available": path is not None}
    if path and version_args is not None:
        result["versionCheck"] = run(command + version_args)
    return result


def npm_package_version(package_name):
    package_json = ROOT / "node_modules" / package_name / "package.json"
    if package_name == "agent-device":
        package_json = ROOT / "node_modules" / "agent-device" / "package.json"
    if not package_json.exists():
        return None
    return json.loads(package_json.read_text()).get("version")


def main():
    loaded_local_env = load_local_env()
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--deep", action="store_true", help="Run slower package doctor commands.")
    args = parser.parse_args()

    node_cmd = [str(LOCAL_NODE)] if LOCAL_NODE.exists() else ["node"]
    node_version = run(node_cmd + ["--version"])
    node_semver = semver_tuple(node_version.get("stdout", ""))
    agent_device_required = (22, 19, 0)
    tool_env = repo_tool_env()

    checks = {
        "host": {
            "platform": platform.platform(),
            "machine": platform.machine(),
        },
        "commands": {
            "git": check_command("git", ["git"], ["--version"]),
            "xcodebuild": check_command("xcodebuild", ["xcodebuild"], ["-version"]),
            "xcrun": check_command("xcrun", ["xcrun"], ["--version"]),
            "codex": check_command("codex", ["codex"], ["--version"]),
            "node": {"available": node_version["ok"], "version": node_version.get("stdout"), "path": node_cmd[0]},
            "npm": check_command("npm", ["npm"], ["--version"]),
        },
        "nodeEngine": {
            "current": node_version.get("stdout"),
            "agentDeviceRequired": ">=22.19.0",
            "ok": node_semver is not None and node_semver >= agent_device_required,
            "note": "agent-device may start on older Node, but real experiment runs should satisfy package engines.",
        },
        "npmPackages": {
            "agent-device": {
                "expected": "0.17.3",
                "installed": npm_package_version("agent-device"),
                "bin": str(ROOT / "node_modules" / ".bin" / "agent-device"),
                "versionCheck": run([str(ROOT / "node_modules" / ".bin" / "agent-device"), "--version"], env=tool_env),
            },
            "xcodebuildmcp": {
                "expected": "2.6.2",
                "installed": npm_package_version("xcodebuildmcp"),
                "bin": str(ROOT / "node_modules" / ".bin" / "xcodebuildmcp"),
                "versionCheck": run([str(ROOT / "node_modules" / ".bin" / "xcodebuildmcp"), "--version"], env=tool_env),
            },
        },
        "mobile": {
            "simulators": run(["xcrun", "simctl", "list", "devices", "available", "--json"], timeout=60),
            "devices": run(["xcrun", "devicectl", "list", "devices", "--json-output", "/tmp/looplab-devices.json"], timeout=60),
        },
        "environment": {
            "LOOPLAB_DEVICE_ID": bool(os.environ.get("LOOPLAB_DEVICE_ID")),
            "LOOPLAB_DEVELOPMENT_TEAM": bool(os.environ.get("LOOPLAB_DEVELOPMENT_TEAM")),
            "localEnvPath": str(LOCAL_ENV),
            "localEnvPresent": LOCAL_ENV.exists(),
            "localEnvLoadedKeys": sorted(loaded_local_env),
        },
    }

    if args.deep:
        checks["xcodebuildmcpDoctor"] = run([str(ROOT / "node_modules" / ".bin" / "xcodebuildmcp-doctor")], timeout=120)

    failed = []
    for name, package in checks["npmPackages"].items():
        if package["installed"] != package["expected"] or not package["versionCheck"]["ok"]:
            failed.append(f"package:{name}")
    if not checks["nodeEngine"]["ok"]:
        failed.append("node-engine")
    for name, command in checks["commands"].items():
        if not command.get("available", False):
            failed.append(f"command:{name}")

    checks["summary"] = {"ok": not failed, "failed": failed}

    if args.json:
        print(json.dumps(checks, indent=2, sort_keys=True))
    else:
        print(f"LoopLab doctor: {'OK' if checks['summary']['ok'] else 'NOT READY'}")
        for failure in failed:
            print(f"- {failure}")
        print(json.dumps(checks["npmPackages"], indent=2, sort_keys=True))
        print(json.dumps(checks["nodeEngine"], indent=2, sort_keys=True))

    raise SystemExit(0 if checks["summary"]["ok"] else 1)


if __name__ == "__main__":
    main()
