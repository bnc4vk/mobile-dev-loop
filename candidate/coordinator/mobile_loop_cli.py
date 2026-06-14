#!/usr/bin/env python3
import argparse
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path


def find_root():
    current = Path.cwd().resolve()
    for path in [current, *current.parents]:
        if (path / "apps" / "LoopLab" / "LoopLab.xcodeproj").exists():
            return path
    return Path(__file__).resolve().parents[2]


ROOT = find_root()
APP_PROJECT = ROOT / "apps" / "LoopLab" / "LoopLab.xcodeproj"
TASKS = ROOT / "experiment" / "public" / "tasks.json"
AGENT_DEVICE = ROOT / "node_modules" / ".bin" / "agent-device"
LOCAL_NODE_BIN = ROOT / "node_modules" / "node" / "bin"


class StepError(RuntimeError):
    def __init__(self, message, result=None):
        super().__init__(message)
        self.result = result


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def command_tail(text, returncode, limit=1000):
    if returncode == 0:
        return ""
    return text[-limit:]


def run(cmd, cwd=ROOT, env=None, check=True, timeout=300):
    started = time.time()
    proc = subprocess.run(cmd, cwd=cwd, env=env, text=True, capture_output=True, timeout=timeout)
    result = {
        "command": cmd,
        "cwd": str(cwd),
        "exitCode": proc.returncode,
        "required": check,
        "durationSeconds": round(time.time() - started, 3),
        "stdoutTail": command_tail(proc.stdout, proc.returncode),
        "stderrTail": command_tail(proc.stderr, proc.returncode),
    }
    if check and proc.returncode != 0:
        raise StepError(f"command failed: {' '.join(cmd)}", result)
    return proc, result


def tool_env(base=None):
    env = dict(base or os.environ)
    if LOCAL_NODE_BIN.exists():
        env["PATH"] = f"{LOCAL_NODE_BIN}{os.pathsep}{env.get('PATH', '')}"
    return env


def free_port():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def physical_device_backend_host():
    for interface in ("en0", "en1"):
        proc = subprocess.run(["ipconfig", "getifaddr", interface], text=True, capture_output=True)
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    finally:
        sock.close()


def load_tasks():
    if not TASKS.exists():
        raise SystemExit(f"task metadata not found: {TASKS}")
    return {task["id"]: task for task in json.loads(TASKS.read_text(encoding="utf-8"))["tasks"]}


def load_task(task_id):
    tasks = load_tasks()
    if task_id not in tasks:
        raise SystemExit(f"unknown task {task_id}; choices: {', '.join(sorted(tasks))}")
    return tasks[task_id]


def run_dir(task_id):
    stamp = time.strftime("%Y%m%d-%H%M%S")
    safe_task = re.sub(r"[^A-Za-z0-9._-]", "-", task_id)
    path = ROOT / "runs" / f"mobile-loop-{safe_task}-{stamp}"
    path.mkdir(parents=True, exist_ok=False)
    return path


def backend_fixture_for_task(task):
    return task.get("fixture", "clean")


def start_backend(task, target, out_dir, commands):
    port = free_port()
    bind_host = "0.0.0.0" if target == "iphone" else "127.0.0.1"
    url_host = physical_device_backend_host() if target == "iphone" else "127.0.0.1"
    log_path = out_dir / "backend.log"
    fixture = backend_fixture_for_task(task)
    cmd = [
        sys.executable,
        str(ROOT / "backend" / "mock_backend.py"),
        "--host",
        bind_host,
        "--port",
        str(port),
        "--fixture",
        fixture,
        "--failure",
        "none",
    ]
    handle = log_path.open("w", encoding="utf-8")
    proc = subprocess.Popen(cmd, cwd=ROOT, stdout=handle, stderr=subprocess.STDOUT, text=True)
    handle.close()
    health_url = f"http://127.0.0.1:{port}/health"
    deadline = time.time() + 10
    while time.time() < deadline:
        if proc.poll() is not None:
            raise StepError(f"backend exited before readiness; see {log_path}")
        try:
            with urllib.request.urlopen(health_url, timeout=0.5) as response:
                if response.status == 200:
                    break
        except Exception:
            time.sleep(0.1)
    else:
        proc.terminate()
        raise StepError(f"backend did not become ready; see {log_path}")
    commands.append({
        "command": cmd,
        "event": "backend_started",
        "pid": proc.pid,
        "fixture": fixture,
        "failure": "none",
        "bindHost": bind_host,
        "urlHost": url_host,
        "port": port,
        "log": str(log_path),
    })
    return proc, f"http://{url_host}:{port}"


def build_simulator(out_dir, commands):
    derived_data = out_dir / "DerivedData"
    cmd = [
        "xcodebuild",
        "-project",
        str(APP_PROJECT),
        "-scheme",
        "LoopLab",
        "-configuration",
        "Debug",
        "-sdk",
        "iphonesimulator",
        "-derivedDataPath",
        str(derived_data),
        "CODE_SIGNING_ALLOWED=NO",
        "build",
    ]
    _, result = run(cmd, cwd=ROOT)
    commands.append(result)
    return derived_data / "Build" / "Products" / "Debug-iphonesimulator" / "LoopLab.app"


def build_iphone(out_dir, device_id, development_team, commands):
    if not device_id:
        raise StepError("physical iPhone validation requires --device-id or LOOPLAB_DEVICE_ID")
    if not development_team:
        raise StepError("physical iPhone validation requires --development-team or LOOPLAB_DEVELOPMENT_TEAM")
    derived_data = out_dir / "DerivedData"
    cmd = [
        "xcodebuild",
        "-project",
        str(APP_PROJECT),
        "-scheme",
        "LoopLab",
        "-configuration",
        "Debug",
        "-sdk",
        "iphoneos",
        "-destination",
        f"id={device_id}",
        "-derivedDataPath",
        str(derived_data),
        "-allowProvisioningUpdates",
        f"DEVELOPMENT_TEAM={development_team}",
        "CODE_SIGN_STYLE=Automatic",
        "build",
    ]
    _, result = run(cmd, cwd=ROOT)
    commands.append(result)
    return derived_data / "Build" / "Products" / "Debug-iphoneos" / "LoopLab.app"


def simulator_udid(commands):
    proc, result = run(["xcrun", "simctl", "list", "devices", "available", "--json"])
    commands.append(result)
    devices = json.loads(proc.stdout)["devices"]
    preferred = []
    for runtime_devices in devices.values():
        preferred.extend(d for d in runtime_devices if "iPhone" in d["name"] and d["isAvailable"])
    if not preferred:
        raise StepError("no available iPhone simulator")
    return preferred[0]["udid"], preferred[0]["name"]


def install_launch_simulator(app, backend_url, commands):
    udid, name = simulator_udid(commands)
    for cmd, check, timeout in [
        (["xcrun", "simctl", "boot", udid], False, 60),
        (["xcrun", "simctl", "bootstatus", udid, "-b"], False, 120),
        (["xcrun", "simctl", "install", udid, str(app)], True, 300),
        (["xcrun", "simctl", "launch", udid, "com.mobiledevloop.LoopLab", f"--backend-url={backend_url}"], True, 120),
    ]:
        _, result = run(cmd, check=check, timeout=timeout)
        commands.append(result)
    return udid, name


def install_launch_iphone(app, backend_url, device_id, out_dir, commands):
    install_json = out_dir / "devicectl-install.json"
    launch_json = out_dir / "devicectl-launch.json"
    install_cmd = ["xcrun", "devicectl", "device", "install", "app", "--device", device_id, str(app), "--json-output", str(install_json)]
    _, result = run(install_cmd, timeout=300)
    commands.append(result)
    launch_cmd = [
        "xcrun",
        "devicectl",
        "device",
        "process",
        "launch",
        "--device",
        device_id,
        "--terminate-existing",
        "com.mobiledevloop.LoopLab",
        f"--backend-url={backend_url}",
        "--json-output",
        str(launch_json),
    ]
    _, result = run(launch_cmd, timeout=120)
    commands.append(result)
    return device_id


def agent_device_env(target, out_dir, development_team):
    env = tool_env()
    env["AGENT_DEVICE_IOS_RUNNER_LEASE_DIR"] = str(out_dir / "agent-device-runner-leases")
    if target == "iphone":
        if development_team:
            env["AGENT_DEVICE_IOS_TEAM_ID"] = development_team
        env.setdefault("AGENT_DEVICE_IOS_BUNDLE_ID", "com.mobiledevloop.agentdevice.runner")
    return env


def capture_evidence(task, target, device_id, backend_url, out_dir, development_team, commands):
    evidence_dir = out_dir / "evidence"
    state_dir = out_dir / "agent-device-state"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)
    env = agent_device_env(target, out_dir, development_team)
    common = [
        str(AGENT_DEVICE),
        "--state-dir",
        str(state_dir),
        "--platform",
        "ios",
        "--udid",
        device_id,
        "--session",
        out_dir.name,
    ]
    _, result = run(common + ["close"], env=env, check=False, timeout=60)
    commands.append(result)
    if target == "iphone":
        _, result = run(common + ["prepare", "ios-runner", "--timeout", "240000", "--json"], env=env, check=False, timeout=300)
        commands.append(result)
    open_cmd = common + ["open", "com.mobiledevloop.LoopLab"]
    if target != "iphone":
        open_cmd.append("--relaunch")
    open_cmd += ["--launch-args", f"--backend-url={backend_url}", "--json"]
    open_proc, result = run(open_cmd, env=env, check=False, timeout=120)
    commands.append(result)
    time.sleep(0.5)

    screenshot = evidence_dir / "agent-device-screenshot.png"
    snapshot = evidence_dir / "agent-device-snapshot.txt"
    screenshot_proc, result = run(common + ["screenshot", str(screenshot), "--json"], env=env, check=False, timeout=120)
    commands.append(result)
    snapshot_proc, result = run(common + ["snapshot"], env=env, check=False, timeout=120)
    commands.append(result)
    if snapshot_proc.stdout:
        snapshot.write_text(snapshot_proc.stdout, encoding="utf-8")

    extra = []
    for screen in task.get("evidenceScreens", []):
        name = screen["name"]
        press_label = screen.get("pressLabel")
        if press_label:
            press_proc, result = run(common + ["press", f'label="{press_label}"'], env=env, check=False, timeout=120)
            commands.append(result)
        else:
            press_proc = None
        time.sleep(0.5)
        extra_screenshot = evidence_dir / f"agent-device-{name}-screenshot.png"
        extra_snapshot = evidence_dir / f"agent-device-{name}-snapshot.txt"
        extra_screenshot_proc, result = run(common + ["screenshot", str(extra_screenshot), "--json"], env=env, check=False, timeout=120)
        commands.append(result)
        extra_snapshot_proc, result = run(common + ["snapshot"], env=env, check=False, timeout=120)
        commands.append(result)
        if extra_snapshot_proc.stdout:
            extra_snapshot.write_text(extra_snapshot_proc.stdout, encoding="utf-8")
        extra.append({
            "name": name,
            "pressLabel": press_label,
            "pressExitCode": press_proc.returncode if press_proc else None,
            "screenshot": str(extra_screenshot) if extra_screenshot.exists() else None,
            "snapshot": str(extra_snapshot) if extra_snapshot.exists() else None,
            "screenshotExitCode": extra_screenshot_proc.returncode,
            "snapshotExitCode": extra_snapshot_proc.returncode,
        })
    _, result = run(common + ["close"], env=env, check=False, timeout=60)
    commands.append(result)

    return {
        "stateDir": str(state_dir),
        "screenshot": str(screenshot) if screenshot.exists() else None,
        "snapshot": str(snapshot) if snapshot.exists() else None,
        "openExitCode": open_proc.returncode,
        "screenshotExitCode": screenshot_proc.returncode,
        "snapshotExitCode": snapshot_proc.returncode,
        "extra": extra,
    }


def expected_texts(task):
    if task["id"] == "T08-camera-surface-iphone":
        return ["Camera"], []
    return ["Clean Account", "Fresh fixture", "alpha", "bravo"], ["Unknown", "Not loaded"]


def evaluate_public_evidence(task, evidence):
    snapshot_path = evidence.get("snapshot")
    snapshot = Path(snapshot_path).read_text(encoding="utf-8") if snapshot_path and Path(snapshot_path).exists() else ""
    required, forbidden = expected_texts(task)
    required_results = {text: text in snapshot for text in required}
    forbidden_results = {text: text not in snapshot for text in forbidden}
    extra_results = {}
    for item in evidence.get("extra", []):
        item_snapshot = item.get("snapshot")
        text = Path(item_snapshot).read_text(encoding="utf-8") if item_snapshot and Path(item_snapshot).exists() else ""
        extra_results[item["name"]] = {
            "snapshot": item_snapshot,
            "screenshot": item.get("screenshot"),
            "hasCameraText": "Camera" in text or "camera" in text,
            "hasPermissionText": "permission" in text.lower() or "authorized" in text.lower() or "not determined" in text.lower() or "denied" in text.lower(),
        }
    pass_basic = bool(
        evidence.get("openExitCode") == 0
        and evidence.get("screenshotExitCode") == 0
        and evidence.get("snapshotExitCode") == 0
        and evidence.get("screenshot")
        and evidence.get("snapshot")
        and all(required_results.values())
        and all(forbidden_results.values())
    )
    if task["id"] == "T08-camera-surface-iphone" and extra_results:
        pass_basic = pass_basic and any(item["hasCameraText"] for item in extra_results.values())
    return {
        "passed": pass_basic,
        "requiredText": required_results,
        "forbiddenTextAbsent": forbidden_results,
        "extra": extra_results,
    }


def status(args):
    tasks = load_tasks()
    latest = sorted((ROOT / "runs").glob("mobile-loop-*"), key=lambda path: path.stat().st_mtime, reverse=True) if (ROOT / "runs").exists() else []
    return {
        "schemaVersion": 1,
        "root": str(ROOT),
        "agentDevice": str(AGENT_DEVICE),
        "agentDevicePresent": AGENT_DEVICE.exists(),
        "tasks": sorted(tasks),
        "latestRun": str(latest[0]) if latest else None,
    }


def preflight(args):
    task = load_task(args.task)
    target = args.target or task["target"]
    return {
        "schemaVersion": 1,
        "taskId": task["id"],
        "target": target,
        "fixture": task.get("fixture"),
        "root": str(ROOT),
        "agentDevicePresent": AGENT_DEVICE.exists(),
        "xcodeProjectPresent": APP_PROJECT.exists(),
        "deviceIdPresent": bool(args.device_id or os.environ.get("LOOPLAB_DEVICE_ID")),
        "developmentTeamPresent": bool(args.development_team or os.environ.get("LOOPLAB_DEVELOPMENT_TEAM")),
        "recommendedCommand": f"mobile-loop validate --task {task['id']}",
    }


def validate(args):
    task = load_task(args.task)
    target = args.target or task["target"]
    device_id = args.device_id or os.environ.get("LOOPLAB_DEVICE_ID")
    development_team = args.development_team or os.environ.get("LOOPLAB_DEVELOPMENT_TEAM")
    out_dir = Path(args.output_dir) if args.output_dir else run_dir(task["id"])
    out_dir.mkdir(parents=True, exist_ok=True)
    commands = []
    backend = None
    payload = {
        "schemaVersion": 1,
        "taskId": task["id"],
        "target": target,
        "runDir": str(out_dir),
        "startedAtMs": int(time.time() * 1000),
        "status": "running",
    }
    try:
        backend, backend_url = start_backend(task, target, out_dir, commands)
        if target == "simulator":
            app = build_simulator(out_dir, commands)
            resolved_device_id, device_name = install_launch_simulator(app, backend_url, commands)
        else:
            app = build_iphone(out_dir, device_id, development_team, commands)
            resolved_device_id = install_launch_iphone(app, backend_url, device_id, out_dir, commands)
            device_name = None
        evidence = capture_evidence(task, target, resolved_device_id, backend_url, out_dir, development_team, commands)
        public_eval = evaluate_public_evidence(task, evidence)
        payload.update({
            "status": "completed",
            "passed": public_eval["passed"],
            "backendUrl": backend_url,
            "artifact": str(app),
            "device": {
                "id": resolved_device_id,
                "name": device_name,
            },
            "evidence": evidence,
            "publicEvaluation": public_eval,
        })
    except Exception as error:
        payload.update({
            "status": "failed",
            "passed": False,
            "error": str(error),
        })
        if isinstance(error, StepError) and error.result:
            payload["failedCommand"] = error.result
    finally:
        if backend is not None:
            backend.terminate()
            try:
                backend.wait(timeout=5)
            except subprocess.TimeoutExpired:
                backend.kill()
                backend.wait(timeout=5)
        payload["commands"] = commands
        payload["finishedAtMs"] = int(time.time() * 1000)
        write_json(out_dir / "mobile-loop-result.json", payload)
    return payload


def terminal_payload(args, payload):
    if args.command != "validate" or getattr(args, "verbose", False):
        return payload
    compact = dict(payload)
    commands = compact.pop("commands", [])
    compact["commandsSummary"] = {
        "count": len(commands),
        "failed": [
            {
                "command": item.get("command"),
                "exitCode": item.get("exitCode"),
                "durationSeconds": item.get("durationSeconds"),
                "stderrTail": item.get("stderrTail"),
            }
            for item in commands
            if isinstance(item, dict) and item.get("required") and item.get("exitCode") not in (None, 0)
        ],
        "nonRequiredNonZeroCount": sum(
            1
            for item in commands
            if isinstance(item, dict) and not item.get("required") and item.get("exitCode") not in (None, 0)
        ),
        "fullLog": str(Path(compact["runDir"]) / "mobile-loop-result.json") if compact.get("runDir") else None,
    }
    return compact


def main():
    parser = argparse.ArgumentParser(prog="mobile-loop")
    subparsers = parser.add_subparsers(dest="command", required=True)

    status_parser = subparsers.add_parser("status")
    status_parser.set_defaults(func=status)

    preflight_parser = subparsers.add_parser("preflight")
    preflight_parser.add_argument("--task", required=True)
    preflight_parser.add_argument("--target", choices=["simulator", "iphone"])
    preflight_parser.add_argument("--device-id", default=os.environ.get("LOOPLAB_DEVICE_ID"))
    preflight_parser.add_argument("--development-team", default=os.environ.get("LOOPLAB_DEVELOPMENT_TEAM"))
    preflight_parser.set_defaults(func=preflight)

    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--task", required=True)
    validate_parser.add_argument("--target", choices=["simulator", "iphone"])
    validate_parser.add_argument("--device-id", default=os.environ.get("LOOPLAB_DEVICE_ID"))
    validate_parser.add_argument("--development-team", default=os.environ.get("LOOPLAB_DEVELOPMENT_TEAM"))
    validate_parser.add_argument("--output-dir")
    validate_parser.add_argument("--verbose", action="store_true", help="print full command details instead of a compact summary")
    validate_parser.set_defaults(func=validate)

    args = parser.parse_args()
    payload = args.func(args)
    print(json.dumps(terminal_payload(args, payload), indent=2, sort_keys=True))
    if payload.get("passed") is False or payload.get("status") == "failed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
