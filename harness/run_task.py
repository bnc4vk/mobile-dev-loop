#!/usr/bin/env python3
import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import uuid
import urllib.request
from pathlib import Path

from metrics import write_metrics
from telemetry import Telemetry, git_head, sha256_path


ROOT = Path(__file__).resolve().parents[1]
APP_PROJECT = ROOT / "apps" / "LoopLab" / "LoopLab.xcodeproj"
RUNS = ROOT / "runs"
TASKS = ROOT / "experiment" / "public" / "tasks.json"
TOOL_LOCK = ROOT / "experiment" / "public" / "tool-versions.lock.json"
FAULTS = ROOT / "experiment" / "private" / "faults" / "fault_profiles.json"
AGENT_DEVICE = ROOT / "node_modules" / ".bin" / "agent-device"


def run(cmd, telemetry, cwd=ROOT, env=None, check=True, timeout=300):
    started = time.time()
    telemetry.emit("command_started", command=cmd, cwd=str(cwd), timeoutSeconds=timeout)
    try:
        proc = subprocess.run(cmd, cwd=cwd, env=env, text=True, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as error:
        telemetry.emit(
            "command_timeout",
            command=cmd,
            cwd=str(cwd),
            timeoutSeconds=timeout,
            durationSeconds=round(time.time() - started, 3),
            stdout=(error.stdout or "")[-4000:] if isinstance(error.stdout, str) else "",
            stderr=(error.stderr or "")[-4000:] if isinstance(error.stderr, str) else "",
        )
        raise
    telemetry.emit(
        "command_finished",
        command=cmd,
        cwd=str(cwd),
        exitCode=proc.returncode,
        durationSeconds=round(time.time() - started, 3),
        stdout=proc.stdout[-4000:],
        stderr=proc.stderr[-4000:],
    )
    if check and proc.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(cmd)}")
    return proc


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


def load_task(task_id):
    tasks = json.loads(TASKS.read_text())["tasks"]
    for task in tasks:
        if task["id"] == task_id:
            return task
    raise SystemExit(f"unknown task {task_id}")


def load_tool_lock():
    return json.loads(TOOL_LOCK.read_text(encoding="utf-8"))


def load_fault_profile(task):
    fault_id = task.get("fault", "none")
    if fault_id == "none":
        return {"id": "none"}
    if not FAULTS.exists():
        raise SystemExit(f"fault profile {fault_id} requested but {FAULTS} does not exist")
    profiles = json.loads(FAULTS.read_text(encoding="utf-8"))["profiles"]
    if fault_id not in profiles:
        raise SystemExit(f"unknown fault profile {fault_id}; choices: {', '.join(sorted(profiles))}")
    return {"id": fault_id, **profiles[fault_id]}


def create_worktree(run_dir, telemetry):
    worktree = run_dir / "worktree"
    run(["git", "worktree", "add", "--detach", str(worktree), "HEAD"], telemetry)
    private_dir = worktree / "experiment" / "private"
    if private_dir.exists():
        shutil.rmtree(private_dir)
        telemetry.emit("private_assets_removed", path=str(private_dir))
    root_node_modules = ROOT / "node_modules"
    worktree_node_modules = worktree / "node_modules"
    if root_node_modules.exists() and not worktree_node_modules.exists():
        worktree_node_modules.symlink_to(root_node_modules, target_is_directory=True)
        telemetry.emit("shared_tooling_linked", source=str(root_node_modules), path=str(worktree_node_modules))
    return worktree


def start_backend(task, run_dir, telemetry, target, fault_profile):
    port = free_port()
    bind_host = "0.0.0.0" if target == "iphone" else "127.0.0.1"
    url_host = physical_device_backend_host() if target == "iphone" else "127.0.0.1"
    fixture = fault_profile.get("backendFixtureOverride", task["fixture"])
    failure = fault_profile.get("backendFailure", "none")
    log_path = run_dir / "backend.log"
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
        failure,
    ]
    handle = log_path.open("w", encoding="utf-8")
    proc = subprocess.Popen(cmd, cwd=ROOT, stdout=handle, stderr=subprocess.STDOUT, text=True)
    health_url = f"http://127.0.0.1:{port}/health"
    deadline = time.time() + 10
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"backend exited before readiness; see {log_path}")
        try:
            with urllib.request.urlopen(health_url, timeout=0.5) as response:
                if response.status == 200:
                    break
        except Exception:
            time.sleep(0.1)
    else:
        proc.terminate()
        raise RuntimeError(f"backend did not become ready; see {log_path}")
    telemetry.emit(
        "backend_started",
        pid=proc.pid,
        port=port,
        bindHost=bind_host,
        urlHost=url_host,
        requestedFixture=task["fixture"],
        fixture=fixture,
        failure=failure,
        log=str(log_path),
    )
    return proc, f"http://{url_host}:{port}"


def build_simulator(worktree, run_dir, backend_url, telemetry):
    derived_data = run_dir / "DerivedData"
    cmd = [
        "xcodebuild",
        "-project",
        str(worktree / "apps" / "LoopLab" / "LoopLab.xcodeproj"),
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
    run(cmd, telemetry, cwd=worktree)
    app = derived_data / "Build" / "Products" / "Debug-iphonesimulator" / "LoopLab.app"
    telemetry.emit("artifact_built", platform="iphonesimulator", path=str(app), sha256=sha256_path(app), backendUrl=backend_url)
    return app


def build_iphone(worktree, run_dir, backend_url, telemetry, device_id, development_team):
    if not device_id:
        raise SystemExit("physical iPhone target requires --device-id or LOOPLAB_DEVICE_ID")
    if not development_team:
        raise SystemExit("physical iPhone target requires --development-team or LOOPLAB_DEVELOPMENT_TEAM")

    derived_data = run_dir / "DerivedData"
    cmd = [
        "xcodebuild",
        "-project",
        str(worktree / "apps" / "LoopLab" / "LoopLab.xcodeproj"),
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
    run(cmd, telemetry, cwd=worktree)
    app = derived_data / "Build" / "Products" / "Debug-iphoneos" / "LoopLab.app"
    telemetry.emit("artifact_built", platform="iphoneos", path=str(app), sha256=sha256_path(app), backendUrl=backend_url)
    return app


def simulator_udid(telemetry):
    proc = run(["xcrun", "simctl", "list", "devices", "available", "--json"], telemetry)
    devices = json.loads(proc.stdout)["devices"]
    preferred = []
    for runtime_devices in devices.values():
        preferred.extend(d for d in runtime_devices if "iPhone" in d["name"] and d["isAvailable"])
    if not preferred:
        raise RuntimeError("no available iPhone simulator")
    return preferred[0]["udid"], preferred[0]["name"]


def app_executable(app):
    return app / "LoopLab"


def apply_fault_before_install(app, run_dir, telemetry, fault_profile):
    if not fault_profile.get("corruptAppBundleBeforeInstall"):
        return
    executable = app_executable(app)
    info_plist = app / "Info.plist"
    if executable.exists():
        executable.unlink()
    if info_plist.exists():
        info_plist.unlink()
    telemetry.emit(
        "fault_injected",
        fault=fault_profile["id"],
        hook="before_install",
        action="corrupt_app_bundle",
        paths=[str(executable), str(info_plist)],
    )


def runner_lease_path(run_dir, device_id):
    lease_dir = run_dir / "agent-device-runner-leases"
    safe_id = re.sub(r"[^A-Za-z0-9._-]", "-", device_id) or "unknown-device"
    return lease_dir / f"{safe_id}.json"


def inject_busy_agent_device_runner(run_dir, telemetry, fault_profile, device_id):
    if not fault_profile.get("busyAgentDeviceRunnerBeforeEvidence"):
        return
    path = runner_lease_path(run_dir, device_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schemaVersion": 1,
        "deviceId": device_id,
        "ownerToken": "injected-fault",
        "ownerPid": os.getpid(),
        "sessionId": "injected-fault",
        "port": 65535,
        "xctestrunPath": str(run_dir / "fault-missing.xctestrun"),
        "jsonPath": str(run_dir / "fault-missing.json"),
        "createdAtMs": int(time.time() * 1000),
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    telemetry.emit(
        "fault_injected",
        fault=fault_profile["id"],
        hook="before_evidence",
        action="busy_agent_device_runner",
        path=str(path),
    )


def terminate_app(target, device_id, telemetry):
    if target == "simulator":
        run(["xcrun", "simctl", "terminate", device_id, "com.mobiledevloop.LoopLab"], telemetry, check=False, timeout=60)
        return
    run(["xcrun", "devicectl", "device", "process", "terminate", "--device", device_id, "com.mobiledevloop.LoopLab"], telemetry, check=False, timeout=60)


def apply_fault_after_agent_device_open(target, device_id, telemetry, fault_profile):
    if not fault_profile.get("terminateAppAfterAgentDeviceOpen"):
        return
    terminate_app(target, device_id, telemetry)
    telemetry.emit(
        "fault_injected",
        fault=fault_profile["id"],
        hook="after_agent_device_open",
        action="terminate_app",
        target=target,
        deviceId=device_id,
    )


def install_launch_simulator(app, backend_url, telemetry, run_dir, fault_profile):
    udid, name = simulator_udid(telemetry)
    run(["xcrun", "simctl", "boot", udid], telemetry, check=False, timeout=60)
    run(["xcrun", "simctl", "bootstatus", udid, "-b"], telemetry, check=False, timeout=120)
    apply_fault_before_install(app, run_dir, telemetry, fault_profile)
    run(["xcrun", "simctl", "install", udid, str(app)], telemetry)
    run(["xcrun", "simctl", "launch", udid, "com.mobiledevloop.LoopLab", f"--backend-url={backend_url}"], telemetry)
    telemetry.emit("app_launched", target="simulator", deviceId=udid, deviceName=name, bundleId="com.mobiledevloop.LoopLab")
    return udid, name


def install_launch_iphone(app, backend_url, telemetry, device_id, run_dir, fault_profile):
    install_json = run_dir / "devicectl-install.json"
    launch_json = run_dir / "devicectl-launch.json"
    apply_fault_before_install(app, run_dir, telemetry, fault_profile)
    run(["xcrun", "devicectl", "device", "install", "app", "--device", device_id, str(app), "--json-output", str(install_json)], telemetry)
    telemetry.emit("app_installed", target="iphone", deviceId=device_id, bundleId="com.mobiledevloop.LoopLab", devicectlOutput=str(install_json))
    run(
        [
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
        ],
        telemetry,
    )
    telemetry.emit("app_launched", target="iphone", deviceId=device_id, bundleId="com.mobiledevloop.LoopLab", devicectlOutput=str(launch_json))
    return device_id


def agent_device_env(target, run_dir, development_team=None):
    env = os.environ.copy()
    env.setdefault("AGENT_DEVICE_IOS_RUNNER_LEASE_DIR", str(run_dir / "agent-device-runner-leases"))
    if target == "iphone":
        if development_team:
            env.setdefault("AGENT_DEVICE_IOS_TEAM_ID", development_team)
        env.setdefault("AGENT_DEVICE_IOS_BUNDLE_ID", "com.mobiledevloop.agentdevice.runner")
    return env


def capture_agent_device_evidence(run_dir, telemetry, device_id, target, backend_url, development_team=None, fault_profile=None):
    fault_profile = fault_profile or {"id": "none"}
    evidence_dir = run_dir / "evidence"
    state_dir = run_dir / "agent-device-state"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)
    screenshot = evidence_dir / "agent-device-screenshot.png"
    snapshot = evidence_dir / "agent-device-snapshot.txt"
    common = [str(AGENT_DEVICE), "--state-dir", str(state_dir), "--platform", "ios", "--udid", device_id, "--session", run_dir.name]
    env = agent_device_env(target, run_dir, development_team)

    run(common + ["close"], telemetry, env=env, check=False, timeout=60)
    inject_busy_agent_device_runner(run_dir, telemetry, fault_profile, device_id)
    if target == "iphone":
        run(common + ["prepare", "ios-runner", "--timeout", "240000", "--json"], telemetry, env=env, check=False, timeout=300)
    open_cmd = common + ["open", "com.mobiledevloop.LoopLab"]
    if target != "iphone":
        open_cmd.append("--relaunch")
    open_cmd += ["--launch-args", f"--backend-url={backend_url}", "--json"]
    open_proc = run(open_cmd, telemetry, env=env, check=False, timeout=120)
    apply_fault_after_agent_device_open(target, device_id, telemetry, fault_profile)
    time.sleep(0.5)
    screenshot_proc = run(common + ["screenshot", str(screenshot), "--json"], telemetry, env=env, check=False, timeout=120)
    snapshot_proc = run(common + ["snapshot"], telemetry, env=env, check=False, timeout=120)
    close_proc = run(common + ["close"], telemetry, env=env, check=False, timeout=60)
    if snapshot_proc.stdout:
        snapshot.write_text(snapshot_proc.stdout, encoding="utf-8")

    telemetry.emit(
        "agent_device_evidence_captured",
        target=target,
        deviceId=device_id,
        stateDir=str(state_dir),
        screenshot=str(screenshot) if screenshot.exists() else None,
        snapshot=str(snapshot) if snapshot.exists() else None,
        openExitCode=open_proc.returncode,
        screenshotExitCode=screenshot_proc.returncode,
        snapshotExitCode=snapshot_proc.returncode,
        closeExitCode=close_proc.returncode,
    )


def write_manifest(run_dir, manifest):
    path = run_dir / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return path


def execute_codex(task, worktree, run_dir, telemetry):
    prompt_path = ROOT / task["promptFile"]
    prompt = prompt_path.read_text(encoding="utf-8")
    events_path = run_dir / "codex-events.jsonl"
    last_message_path = run_dir / "codex-last-message.md"
    cmd = [
        "codex",
        "exec",
        "--cd",
        str(worktree),
        "--json",
        "--output-last-message",
        str(last_message_path),
        "-",
    ]
    telemetry.emit("agent_thread_started", tool="codex", promptFile=str(prompt_path), eventsPath=str(events_path), lastMessagePath=str(last_message_path))
    started = time.time()
    with events_path.open("w", encoding="utf-8") as events:
        proc = subprocess.run(cmd, input=prompt, cwd=worktree, text=True, stdout=events, stderr=subprocess.PIPE, timeout=7200)
    telemetry.emit(
        "agent_thread_finished",
        tool="codex",
        exitCode=proc.returncode,
        durationSeconds=round(time.time() - started, 3),
        stderr=proc.stderr[-4000:],
    )
    if proc.returncode != 0:
        raise RuntimeError("codex executor failed")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True)
    parser.add_argument("--condition", choices=["baseline", "candidate"], required=True)
    parser.add_argument("--target", choices=["simulator", "iphone"], default=None)
    parser.add_argument("--device-id", default=os.environ.get("LOOPLAB_DEVICE_ID"))
    parser.add_argument("--development-team", default=os.environ.get("LOOPLAB_DEVELOPMENT_TEAM"))
    parser.add_argument("--execute-agent", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    task = load_task(args.task)
    tool_lock = load_tool_lock()
    fault_profile = load_fault_profile(task)
    target = args.target or task["target"]
    run_id = f"{args.task}-{args.condition}-{uuid.uuid4().hex[:10]}"
    run_dir = RUNS / run_id
    run_dir.mkdir(parents=True)
    telemetry = Telemetry(run_dir / "telemetry.jsonl")
    source_head = git_head(ROOT)
    telemetry.emit("run_started", runId=run_id, task=args.task, condition=args.condition, target=target, sourceHead=source_head, toolLock=tool_lock)
    telemetry.emit("fault_profile_loaded", fault=task.get("fault", "none"), profileId=fault_profile["id"])

    backend = None
    try:
        if args.dry_run:
            telemetry.emit("dry_run_complete")
            manifest = write_manifest(run_dir, {"runId": run_id, "task": task, "condition": args.condition, "target": target, "sourceHead": source_head, "dryRun": True, "toolLock": tool_lock})
            print(manifest)
            return

        worktree = create_worktree(run_dir, telemetry)
        backend, backend_url = start_backend(task, run_dir, telemetry, target, fault_profile)

        if args.execute_agent:
            execute_codex(task, worktree, run_dir, telemetry)

        if target == "simulator":
            app = build_simulator(worktree, run_dir, backend_url, telemetry)
            device_id, _ = install_launch_simulator(app, backend_url, telemetry, run_dir, fault_profile)
            capture_agent_device_evidence(run_dir, telemetry, device_id, target, backend_url, fault_profile=fault_profile)
        else:
            app = build_iphone(worktree, run_dir, backend_url, telemetry, args.device_id, args.development_team)
            device_id = install_launch_iphone(app, backend_url, telemetry, args.device_id, run_dir, fault_profile)
            capture_agent_device_evidence(run_dir, telemetry, device_id, target, backend_url, args.development_team, fault_profile)

        manifest = write_manifest(run_dir, {"runId": run_id, "task": task, "condition": args.condition, "target": target, "sourceHead": source_head, "status": "completed", "toolLock": tool_lock})
        telemetry.emit("run_finished", manifest=str(manifest))
        _, metrics_path = write_metrics(run_dir)
        telemetry.emit("metrics_written", path=str(metrics_path))
        print(manifest)
    except Exception as error:
        telemetry.emit("run_failed", errorType=type(error).__name__, error=str(error))
        manifest = write_manifest(run_dir, {
            "runId": run_id,
            "task": task,
            "condition": args.condition,
            "target": target,
            "sourceHead": source_head,
            "status": "failed",
            "error": str(error),
            "toolLock": tool_lock,
        })
        _, metrics_path = write_metrics(run_dir)
        telemetry.emit("metrics_written", path=str(metrics_path))
        print(manifest)
        raise
    finally:
        if backend is not None:
            backend.terminate()
            telemetry.emit("backend_terminated", pid=backend.pid)


if __name__ == "__main__":
    main()
