#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path

from local_config import LOCAL_ENV, load_local_env


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "runs" / "locks" / "experiment-lock.json"
LOCKED_ROOTS = [
    ROOT / "apps" / "LoopLab",
    ROOT / "backend",
    ROOT / "harness",
    ROOT / "candidate",
    ROOT / "experiment" / "public",
    ROOT / "experiment" / "private",
    ROOT / "docs",
    ROOT / "tests",
]
SKIP_NAMES = {
    "__pycache__",
    ".DS_Store",
    "experiment-lock.json",
}
SKIP_SUFFIXES = {
    ".pyc",
    ".xcuserstate",
}


def run(cmd):
    proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)
    return {
        "command": cmd,
        "exitCode": proc.returncode,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
    }


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def should_include(path):
    if path.name in SKIP_NAMES:
        return False
    if path.suffix in SKIP_SUFFIXES:
        return False
    if "xcuserdata" in path.parts:
        return False
    return path.is_file()


def locked_files():
    files = []
    for root in LOCKED_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if should_include(path):
                files.append(path)
    return sorted(files, key=lambda path: path.relative_to(ROOT).as_posix())


def file_manifest():
    files = []
    aggregate = hashlib.sha256()
    for path in locked_files():
        relative = path.relative_to(ROOT).as_posix()
        digest = sha256_file(path)
        files.append({
            "path": relative,
            "sha256": digest,
            "bytes": path.stat().st_size,
        })
        aggregate.update(relative.encode("utf-8"))
        aggregate.update(b"\0")
        aggregate.update(digest.encode("ascii"))
        aggregate.update(b"\0")
    return files, aggregate.hexdigest()


def git_state():
    return {
        "head": run(["git", "rev-parse", "HEAD"]),
        "statusShort": run(["git", "status", "--short"]),
    }


def tool_state():
    return {
        "toolLock": json.loads((ROOT / "experiment" / "public" / "tool-versions.lock.json").read_text(encoding="utf-8")),
        "packageLockSha256": sha256_file(ROOT / "package-lock.json"),
        "xcodebuild": run(["xcodebuild", "-version"]),
        "agentDevice": run([str(ROOT / "node_modules" / ".bin" / "agent-device"), "--version"]),
        "xcodeBuildMcp": run([str(ROOT / "node_modules" / ".bin" / "xcodebuildmcp"), "--version"]),
    }


def hardware_state(include_devices):
    state = {
        "looplabDeviceIdEnvPresent": bool(os.environ.get("LOOPLAB_DEVICE_ID")),
        "looplabDevelopmentTeamEnvPresent": bool(os.environ.get("LOOPLAB_DEVELOPMENT_TEAM")),
        "localEnvPath": str(LOCAL_ENV),
        "localEnvPresent": LOCAL_ENV.exists(),
    }
    if include_devices:
        state["devicectlDevices"] = run(["xcrun", "devicectl", "list", "devices"])
        state["simctlDevices"] = run(["xcrun", "simctl", "list", "devices", "available", "--json"])
    return state


def build_lock(include_devices):
    files, aggregate = file_manifest()
    return {
        "schemaVersion": 1,
        "lockKind": "mobile-dev-loop-experiment",
        "contentSha256": aggregate,
        "files": files,
        "git": git_state(),
        "tools": tool_state(),
        "hardware": hardware_state(include_devices),
        "cachePolicy": {
            "default": "equivalent-cold-start",
            "isolatedState": [
                "worktree",
                "DerivedData",
                "backend process and port",
                "agent-device state",
                "agent-device runner lease",
                "run artifacts"
            ]
        }
    }


def main():
    load_local_env()
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--include-devices", action="store_true")
    args = parser.parse_args()

    payload = build_lock(args.include_devices)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
