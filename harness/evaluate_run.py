#!/usr/bin/env python3
import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from local_config import load_local_env


ROOT = Path(__file__).resolve().parents[1]
ORACLES = ROOT / "experiment" / "private" / "validators" / "task_oracles.json"
AGENT_DEVICE = ROOT / "node_modules" / ".bin" / "agent-device"
BUNDLE_ID = "com.mobiledevloop.LoopLab"


def load_json(path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def check(observations, condition, message, details=None):
    observations.append({
        "passed": bool(condition),
        "message": message,
        **({"details": details} if details is not None else {}),
    })


def run_git(worktree, args):
    proc = subprocess.run(["git", *args], cwd=worktree, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        return None
    return proc.stdout


def run_cmd(cmd, cwd=ROOT, env=None, timeout=120, check=False):
    started = time.time()
    proc = subprocess.run(cmd, cwd=cwd, env=env, text=True, capture_output=True, timeout=timeout, check=False)
    result = {
        "command": cmd,
        "cwd": str(cwd),
        "exitCode": proc.returncode,
        "durationSeconds": round(time.time() - started, 3),
        "stdout": proc.stdout[-4000:],
        "stderr": proc.stderr[-4000:],
    }
    if check and proc.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(cmd)}")
    return proc, result


def changed_files(worktree, base):
    text = run_git(worktree, ["diff", "--name-only", base, "--"])
    return [line for line in (text or "").splitlines() if line.strip()]


def final_diff(worktree, base, run_dir):
    text = run_git(worktree, ["diff", base, "--"]) or ""
    path = run_dir / "final-source.diff"
    path.write_text(text, encoding="utf-8")
    return text, path


def production_changes(files):
    return [
        path
        for path in files
        if path.startswith("apps/LoopLab/LoopLab/")
        and (path.endswith(".swift") or path.endswith(".plist"))
    ]


def forbidden_changes(files):
    prefixes = ("harness/", "experiment/private/", "experiment/public/tasks.json", "backend/fixtures.json")
    return [path for path in files if path.startswith(prefixes)]


def max_mtime_ms(worktree, files):
    mtimes = []
    for rel in files:
        path = Path(worktree) / rel
        if path.exists():
            mtimes.append(int(path.stat().st_mtime * 1000))
    return max(mtimes) if mtimes else None


def max_tree_mtime_ms(path):
    path = Path(path)
    if not path.exists():
        return None
    if path.is_file():
        return int(path.stat().st_mtime * 1000)
    mtimes = [int(child.stat().st_mtime * 1000) for child in path.rglob("*") if child.exists()]
    return max(mtimes) if mtimes else int(path.stat().st_mtime * 1000)


def text_from_paths(paths):
    output = []
    for value in paths or []:
        path = Path(value)
        if path.exists() and path.is_file():
            try:
                output.append(path.read_text(encoding="utf-8", errors="ignore"))
            except OSError:
                pass
    return "\n".join(output)


def newest_looplab_app(run_dir, worktree):
    candidates = []
    roots = [Path(run_dir), Path(worktree)] if worktree else [Path(run_dir)]
    for root in roots:
        if root.exists():
            candidates.extend(path for path in root.rglob("LoopLab.app") if path.is_dir())
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def artifact_from_state_or_disk(state, run_dir, worktree):
    build = state.get("build") or {}
    artifact_path = build.get("artifactPath")
    if artifact_path and Path(artifact_path).exists():
        return Path(artifact_path), build.get("artifactHash"), "mobile-dev-state"
    found = newest_looplab_app(run_dir, worktree)
    return (found, None, "reconstructed-disk") if found else (None, None, "missing")


def recorded_evidence_paths(state, run_dir):
    evidence = state.get("evidence") or {}
    paths = [Path(path) for path in evidence.get("paths", [])]
    if paths:
        return paths, "mobile-dev-state"
    roots = [Path(run_dir) / "run-context", Path(run_dir) / "evidence"]
    found = []
    for root in roots:
        if root.exists():
            found.extend(path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in {".txt", ".json", ".png"})
    return found, "reconstructed-disk"


def free_port(preferred=None):
    if preferred is not None:
        probe = socket.socket()
        try:
            probe.bind(("127.0.0.1", preferred))
            probe.close()
            return preferred
        except OSError:
            probe.close()
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def start_validation_backend(run_dir, fixture="clean", failure="none", preferred_port=None):
    port = free_port(preferred_port)
    log_path = run_dir / "validation-backend.log"
    cmd = [
        sys.executable,
        str(ROOT / "backend" / "mock_backend.py"),
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--fixture",
        fixture,
        "--failure",
        failure,
    ]
    handle = log_path.open("w", encoding="utf-8")
    proc = subprocess.Popen(cmd, cwd=ROOT, stdout=handle, stderr=subprocess.STDOUT, text=True)
    handle.close()
    health_url = f"http://127.0.0.1:{port}/health"
    deadline = time.time() + 10
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"validation backend exited before readiness; see {log_path}")
        try:
            with urllib.request.urlopen(health_url, timeout=0.5) as response:
                if response.status == 200:
                    return proc, f"http://127.0.0.1:{port}", str(log_path)
        except Exception:
            time.sleep(0.1)
    proc.terminate()
    raise RuntimeError(f"validation backend did not become ready; see {log_path}")


def http_get_json(url):
    with urllib.request.urlopen(url, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def set_backend_state(backend_url, fixture=None, failure=None, delay_ms=None):
    params = []
    if fixture is not None:
        params.append(f"fixture={fixture}")
    if failure is not None:
        params.append(f"failure={failure}")
    if delay_ms is not None:
        params.append(f"delayMs={int(delay_ms)}")
    return http_get_json(f"{backend_url}/set-state?{'&'.join(params)}")


def set_backend_sequence(backend_url, steps):
    query = "&".join(f"step={fixture}:{delay_ms}:{failure}" for fixture, delay_ms, failure in steps)
    return http_get_json(f"{backend_url}/set-sequence?{query}")


def simulator_udid():
    proc, _ = run_cmd(["xcrun", "simctl", "list", "devices", "available", "--json"], timeout=60, check=True)
    devices = json.loads(proc.stdout)["devices"]
    preferred = []
    for runtime_devices in devices.values():
        preferred.extend(d for d in runtime_devices if "iPhone" in d["name"] and d["isAvailable"])
    if not preferred:
        raise RuntimeError("no available iPhone simulator")
    booted = [device for device in preferred if device.get("state") == "Booted"]
    device = booted[0] if booted else preferred[0]
    return device["udid"], device["name"]


def agent_env(run_dir):
    env = os.environ.copy()
    env["AGENT_DEVICE_IOS_RUNNER_LEASE_DIR"] = str(run_dir / "validator-agent-device-runner-leases")
    if os.environ.get("LOOPLAB_DEVELOPMENT_TEAM"):
        env["AGENT_DEVICE_IOS_TEAM_ID"] = os.environ["LOOPLAB_DEVELOPMENT_TEAM"]
    env.setdefault("AGENT_DEVICE_IOS_BUNDLE_ID", "com.mobiledevloop.agentdevice.runner")
    return env


def agent_common(run_dir, udid):
    state_dir = run_dir / "validator-agent-device-state"
    state_dir.mkdir(parents=True, exist_ok=True)
    return [
        str(AGENT_DEVICE),
        "--state-dir",
        str(state_dir),
        "--platform",
        "ios",
        "--udid",
        udid,
        "--session",
        f"validator-{run_dir.name}",
    ]


def snapshot(run_dir, common, name, commands, env=None):
    evidence_dir = run_dir / "validation-evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    screenshot = evidence_dir / f"{name}.png"
    snapshot_path = evidence_dir / f"{name}.txt"
    _, result = run_cmd(common + ["screenshot", str(screenshot), "--json"], env=env or agent_env(run_dir), timeout=120)
    commands.append(result)
    proc, result = run_cmd(common + ["snapshot"], env=env or agent_env(run_dir), timeout=120)
    commands.append(result)
    snapshot_path.write_text(proc.stdout or "", encoding="utf-8")
    return {"screenshot": str(screenshot), "snapshot": str(snapshot_path), "text": proc.stdout or ""}


def press(common, selector, run_dir, commands, timeout=60, env=None):
    proc, result = run_cmd(common + ["press", selector], env=env or agent_env(run_dir), timeout=timeout)
    commands.append(result)
    return proc.returncode == 0


def agent_cmd(common, args, run_dir, commands, env=None, timeout=120):
    proc, result = run_cmd(common + args, env=env or agent_env(run_dir), timeout=timeout)
    commands.append(result)
    return proc, result


def agent_snapshot_json(common, run_dir, commands, env):
    proc, _ = agent_cmd(common, ["snapshot", "-i", "--json"], run_dir, commands, env=env, timeout=120)
    if proc.returncode != 0:
        return {}
    try:
        return json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return {}


def snapshot_nodes(payload):
    return ((payload.get("data") or {}).get("nodes") or [])


def find_switch_value(nodes, label):
    for node in nodes:
        if node.get("type") == "Switch" and node.get("label") == label:
            return node.get("value")
    return None


def launch_with_agent(common, backend_url, run_dir, commands, relaunch=True):
    launch_cmd = common + ["open", BUNDLE_ID]
    if relaunch:
        launch_cmd.append("--relaunch")
    launch_cmd += ["--launch-args", f"--backend-url={backend_url}", "--json"]
    proc, result = run_cmd(launch_cmd, env=agent_env(run_dir), timeout=120)
    commands.append(result)
    time.sleep(1)
    return proc.returncode == 0


def prepare_ios_runner(common, env, commands, attempts=2):
    last_proc = None
    last_output = ""
    for attempt in range(1, attempts + 1):
        proc, result = run_cmd(common + ["prepare", "ios-runner", "--timeout", "240000", "--json"], env=env, timeout=300)
        result["attempt"] = attempt
        commands.append(result)
        last_proc = proc
        last_output = f"{result.get('stdout', '')}\n{result.get('stderr', '')}"
        try:
            payload = json.loads(result.get("stdout", "") or "{}")
            log_path = payload.get("error", {}).get("logPath")
            if log_path and Path(log_path).exists():
                last_output += "\n" + Path(log_path).read_text(encoding="utf-8", errors="ignore")[-8000:]
        except Exception:
            pass
        if proc.returncode == 0:
            return True
        time.sleep(2)
    if "Timed out while enabling automation mode" in last_output:
        raise RuntimeError("physical iPhone automation mode did not become ready; unlock the device and allow XCTest automation, then retry")
    return False


def direct_permission_result(common, action, permission, run_dir, commands, env):
    proc, result = agent_cmd(common, ["settings", "permission", action, permission, "--json"], run_dir, commands, env=env, timeout=120)
    output = f"{result.get('stdout', '')}\n{result.get('stderr', '')}"
    return proc.returncode == 0, output


def ensure_app_camera_permission_record(common, backend_url, run_dir, commands, env):
    agent_cmd(common, ["open", BUNDLE_ID, "--launch-args", f"--backend-url={backend_url}", "--json"], run_dir, commands, env=env)
    press(common, 'label="Settings"', run_dir, commands, env=env)
    payload = agent_snapshot_json(common, run_dir, commands, env)
    text = json.dumps(payload)
    if "Camera permission: notDetermined" not in text:
        return
    if not press(common, 'label="Request camera permission"', run_dir, commands, env=env):
        raise RuntimeError("could not press LoopLab camera permission request control")
    time.sleep(1)
    prompt = agent_snapshot_json(common, run_dir, commands, env)
    if "“LoopLab” would like to access the Camera." not in json.dumps(prompt):
        return
    if not press(common, 'label="Allow"', run_dir, commands, env=env):
        raise RuntimeError("could not accept LoopLab camera permission prompt")
    time.sleep(1)


def open_looplab_settings_pane(common, run_dir, commands, env):
    agent_cmd(common, ["open", "Settings", "--json"], run_dir, commands, env=env)
    payload = agent_snapshot_json(common, run_dir, commands, env)
    nodes = snapshot_nodes(payload)
    if find_switch_value(nodes, "Camera") is not None:
        return nodes

    # Search survives across Settings launches on physical devices. Try the visible
    # result first, then seed the search field if needed.
    if not press(common, 'label="LoopLab"', run_dir, commands, env=env):
        agent_cmd(common, ["scroll", "top"], run_dir, commands, env=env, timeout=60)
        press(common, 'label="Search"', run_dir, commands, env=env)
        agent_cmd(common, ["fill", 'label="Search"', "LoopLab"], run_dir, commands, env=env)
        time.sleep(1)
        if not press(common, 'label="LoopLab"', run_dir, commands, env=env):
            raise RuntimeError("could not navigate to LoopLab Settings pane")

    time.sleep(1)
    payload = agent_snapshot_json(common, run_dir, commands, env)
    return snapshot_nodes(payload)


def set_camera_permission_with_settings_ui(common, backend_url, desired_value, run_dir, commands, env):
    ensure_app_camera_permission_record(common, backend_url, run_dir, commands, env)
    nodes = open_looplab_settings_pane(common, run_dir, commands, env)
    value = find_switch_value(nodes, "Camera")
    if value is None:
        raise RuntimeError("LoopLab Camera switch was not visible in Settings")
    if value == desired_value:
        return

    # The switch node spans the row on physical iOS. Tapping the visible switch
    # control area, not the row center, reliably changes the value.
    agent_cmd(common, ["press", "350", "234", "--json"], run_dir, commands, env=env)
    time.sleep(1)
    nodes = snapshot_nodes(agent_snapshot_json(common, run_dir, commands, env))
    value = find_switch_value(nodes, "Camera")
    if value != desired_value:
        raise RuntimeError(f"LoopLab Camera switch did not reach value {desired_value}; observed {value}")


def set_camera_permission(common, backend_url, action, run_dir, commands, env):
    succeeded, output = direct_permission_result(common, action, "camera", run_dir, commands, env)
    if succeeded:
        return
    if "UNSUPPORTED_OPERATION" not in output and "not supported on this device" not in output:
        raise RuntimeError(f"agent-device camera permission {action} failed")
    desired_value = "1" if action == "grant" else "0"
    set_camera_permission_with_settings_ui(common, backend_url, desired_value, run_dir, commands, env)


def install_on_simulator(artifact_path, udid, commands):
    for cmd, check, timeout in [
        (["xcrun", "simctl", "boot", udid], False, 60),
        (["xcrun", "simctl", "bootstatus", udid, "-b"], False, 120),
        (["xcrun", "simctl", "uninstall", udid, BUNDLE_ID], False, 60),
        (["xcrun", "simctl", "install", udid, str(artifact_path)], True, 300),
    ]:
        _, result = run_cmd(cmd, timeout=timeout, check=check)
        commands.append(result)


def validate_simulator_task(task_id, artifact_path, run_dir):
    commands = []
    evidence = []
    backend = None
    try:
        fixed_port = 8765 if task_id == "T02-cold-start-deep-link-simulator" else None
        initial_fixture = "malformed" if task_id == "T07-malformed-backend-recovery-simulator" else "clean"
        backend, backend_url, backend_log = start_validation_backend(run_dir, fixture=initial_fixture, preferred_port=fixed_port)
        udid, device_name = simulator_udid()
        install_on_simulator(artifact_path, udid, commands)
        common = agent_common(run_dir, udid)
        run_cmd(common + ["close"], env=agent_env(run_dir), timeout=60)

        if task_id == "T01-record-selection-persistence-simulator":
            launch_with_agent(common, backend_url, run_dir, commands)
            press(common, 'label="alpha"', run_dir, commands)
            press(common, 'label="Select"', run_dir, commands)
            run_cmd(["xcrun", "simctl", "terminate", udid, BUNDLE_ID], timeout=60)
            launch_with_agent(common, backend_url, run_dir, commands)
            evidence.append(snapshot(run_dir, common, "selection-restored", commands))
            set_backend_state(backend_url, fixture="empty")
            press(common, 'label="Reload"', run_dir, commands)
            time.sleep(1)
            evidence.append(snapshot(run_dir, common, "selection-cleared", commands))
        elif task_id == "T02-cold-start-deep-link-simulator":
            run_cmd(["xcrun", "simctl", "terminate", udid, BUNDLE_ID], timeout=60)
            _, result = run_cmd(["xcrun", "simctl", "openurl", udid, "looplab://record/bravo"], timeout=120)
            commands.append(result)
            time.sleep(2)
            evidence.append(snapshot(run_dir, common, "cold-deeplink", commands))
            _, result = run_cmd(["xcrun", "simctl", "openurl", udid, "looplab://record/missing"], timeout=120)
            commands.append(result)
            time.sleep(1)
            evidence.append(snapshot(run_dir, common, "unknown-deeplink", commands))
        elif task_id == "T03-foreground-data-refresh-simulator":
            launch_with_agent(common, backend_url, run_dir, commands)
            set_backend_state(backend_url, fixture="refreshed")
            run_cmd(["xcrun", "simctl", "ui", udid, "home"], timeout=60)
            time.sleep(1)
            run_cmd(["xcrun", "simctl", "launch", udid, BUNDLE_ID, f"--backend-url={backend_url}"], timeout=120)
            time.sleep(2)
            evidence.append(snapshot(run_dir, common, "foreground-refresh", commands))
        elif task_id == "T04-out-of-order-request-protection-simulator":
            launch_with_agent(common, backend_url, run_dir, commands)
            set_backend_sequence(backend_url, [("older", 900, "none"), ("newest", 0, "none")])
            press(common, 'label="Reload"', run_dir, commands)
            press(common, 'label="Reload"', run_dir, commands)
            time.sleep(2)
            evidence.append(snapshot(run_dir, common, "request-order", commands))
        elif task_id == "T05-offline-cached-account-fallback-simulator":
            launch_with_agent(common, backend_url, run_dir, commands)
            set_backend_state(backend_url, failure="http-500")
            run_cmd(["xcrun", "simctl", "terminate", udid, BUNDLE_ID], timeout=60)
            launch_with_agent(common, backend_url, run_dir, commands)
            evidence.append(snapshot(run_dir, common, "offline-cache", commands))
            set_backend_state(backend_url, fixture="refreshed", failure="none")
            press(common, 'label="Reload"', run_dir, commands)
            time.sleep(1)
            evidence.append(snapshot(run_dir, common, "live-recovery", commands))
        elif task_id == "T06-settings-migration-app-update-simulator":
            run_cmd(["xcrun", "simctl", "spawn", udid, "defaults", "write", BUNDLE_ID, "loggedIn", "-bool", "YES"], timeout=60)
            launch_with_agent(common, backend_url, run_dir, commands)
            evidence.append(snapshot(run_dir, common, "settings-migration", commands))
        elif task_id == "T07-malformed-backend-recovery-simulator":
            launch_with_agent(common, backend_url, run_dir, commands)
            evidence.append(snapshot(run_dir, common, "malformed", commands))
            set_backend_state(backend_url, fixture="clean", failure="none")
            press(common, 'label="Reload"', run_dir, commands)
            time.sleep(1)
            evidence.append(snapshot(run_dir, common, "malformed-recovery", commands))

        text = "\n".join(item["text"] for item in evidence)
        return {
            "status": "completed",
            "target": "simulator",
            "deviceId": udid,
            "deviceName": device_name,
            "backendUrl": backend_url,
            "backendLog": backend_log,
            "commands": commands,
            "evidence": [{key: value for key, value in item.items() if key != "text"} for item in evidence],
            "evidenceText": text,
        }
    except Exception as error:
        return {
            "status": "failed",
            "target": "simulator",
            "error": str(error),
            "commands": commands,
            "evidence": [{key: value for key, value in item.items() if key != "text"} for item in evidence],
            "evidenceText": "\n".join(item.get("text", "") for item in evidence),
        }
    finally:
        if backend is not None:
            backend.terminate()


def validate_iphone_task(task_id, artifact_path, run_dir):
    commands = []
    evidence = []
    device_id = os.environ.get("LOOPLAB_DEVICE_ID")
    if not device_id:
        proc, result = run_cmd(["xcrun", "devicectl", "list", "devices"], timeout=60)
        commands.append(result)
        for line in proc.stdout.splitlines():
            parts = line.split()
            for part in parts:
                if part.count("-") == 4 and len(part) >= 32:
                    device_id = part
                    break
            if device_id:
                break
    if not device_id:
        return {
            "status": "skipped",
            "target": "iphone",
            "reason": "no physical iPhone identifier available",
            "evidenceText": "",
            "commands": commands,
            "evidence": [],
        }
    backend = None
    try:
        backend, backend_url, backend_log = start_validation_backend(run_dir, fixture="clean")
        install_json = run_dir / "validation-devicectl-install.json"
        launch_json = run_dir / "validation-devicectl-launch.json"
        _, result = run_cmd(["xcrun", "devicectl", "device", "install", "app", "--device", device_id, str(artifact_path), "--json-output", str(install_json)], timeout=300)
        commands.append(result)
        _, result = run_cmd([
            "xcrun",
            "devicectl",
            "device",
            "process",
            "launch",
            "--device",
            device_id,
            "--terminate-existing",
            BUNDLE_ID,
            f"--backend-url={backend_url}",
            "--json-output",
            str(launch_json),
        ], timeout=120)
        commands.append(result)

        env = agent_env(run_dir)
        team_id = os.environ.get("LOOPLAB_DEVELOPMENT_TEAM")
        if team_id:
            env["AGENT_DEVICE_IOS_TEAM_ID"] = team_id
        env.setdefault("AGENT_DEVICE_IOS_BUNDLE_ID", "com.mobiledevloop.agentdevice.runner")
        common = agent_common(run_dir, device_id)
        if not prepare_ios_runner(common, env, commands, attempts=2):
            raise RuntimeError("agent-device iOS runner did not become ready after retries")
        _, result = run_cmd(common + ["open", BUNDLE_ID, "--launch-args", f"--backend-url={backend_url}", "--json"], env=env, timeout=120)
        commands.append(result)
        press(common, 'label="Camera"', run_dir, commands, env=env)
        set_camera_permission(common, backend_url, "grant", run_dir, commands, env)
        _, result = run_cmd(common + ["open", BUNDLE_ID, "--launch-args", f"--backend-url={backend_url}", "--json"], env=env, timeout=120)
        commands.append(result)
        press(common, 'label="Camera"', run_dir, commands, env=env)
        evidence.append(snapshot(run_dir, common, "iphone-camera-initial-granted", commands, env=env))
        _, result = run_cmd(common + ["home"], env=env, timeout=60)
        commands.append(result)
        set_camera_permission(common, backend_url, "deny", run_dir, commands, env)
        _, result = run_cmd(common + ["open", BUNDLE_ID, "--launch-args", f"--backend-url={backend_url}", "--json"], env=env, timeout=120)
        commands.append(result)
        press(common, 'label="Camera"', run_dir, commands, env=env)
        evidence.append(snapshot(run_dir, common, "iphone-camera-after-deny", commands, env=env))
        return {
            "status": "completed",
            "target": "iphone",
            "deviceId": device_id,
            "backendUrl": backend_url,
            "backendLog": backend_log,
            "commands": commands,
            "evidence": [{key: value for key, value in item.items() if key != "text"} for item in evidence],
            "evidenceText": "\n".join(item.get("text", "") for item in evidence),
        }
    except Exception as error:
        return {
            "status": "failed",
            "target": "iphone",
            "deviceId": device_id,
            "error": str(error),
            "commands": commands,
            "evidence": [{key: value for key, value in item.items() if key != "text"} for item in evidence],
            "evidenceText": "\n".join(item.get("text", "") for item in evidence),
        }
    finally:
        if backend is not None:
            backend.terminate()


def run_mobile_oracle(task_id, target, artifact_path, run_dir):
    if target == "simulator":
        return validate_simulator_task(task_id, artifact_path, run_dir)
    if target == "iphone":
        return validate_iphone_task(task_id, artifact_path, run_dir)
    return {"status": "skipped", "reason": f"unknown target {target}", "evidenceText": "", "commands": [], "evidence": []}


def looks_like_hardcoded_oracle(diff_text, oracle):
    forbidden = oracle.get("hardcodeForbiddenText", [])
    return [text for text in forbidden if text and text in diff_text]


def evaluate(run_dir):
    run_dir = Path(run_dir)
    manifest = load_json(run_dir / "manifest.json", {})
    oracle_set = load_json(ORACLES, {})
    metrics = load_json(run_dir / "metrics.json", {})
    events = load_jsonl(run_dir / "telemetry.jsonl")
    context_dir = Path(manifest.get("runContextDir") or run_dir / "run-context")
    state = load_json(context_dir / "state.json", {})
    ledger = load_jsonl(context_dir / "ledger.jsonl")

    observations = []
    check(observations, bool(manifest), "manifest.json exists")
    check(observations, bool(events), "telemetry.jsonl contains events")
    check(observations, oracle_set is not None, "private oracle file exists")

    task = manifest.get("task", {})
    task_id = task.get("id") or metrics.get("taskId")
    oracle = oracle_set.get("tasks", {}).get(task_id)
    check(observations, oracle is not None, "oracle exists for task", {"taskId": task_id})
    if oracle is None:
        return write_result(run_dir, task_id, "missing-oracle", observations)

    worktree = Path(manifest.get("worktree") or "")
    check(observations, worktree.exists(), "executor worktree exists", {"worktree": str(worktree)})
    check(observations, manifest.get("target") == oracle["expectedTarget"], "target matches oracle", {"actual": manifest.get("target"), "expected": oracle["expectedTarget"]})
    check(observations, oracle.get("initialOracleExpectedFailure") is True, "locked starting revision is declared to fail the initial hidden oracle")

    files = changed_files(worktree, manifest.get("sourceHead", "HEAD")) if worktree.exists() else []
    diff_text, diff_path = final_diff(worktree, manifest.get("sourceHead", "HEAD"), run_dir) if worktree.exists() else ("", run_dir / "final-source.diff")
    prod_files = production_changes(files)
    bad_files = forbidden_changes(files)
    check(observations, bool(prod_files), "production source code changed", {"changedProductionFiles": prod_files})
    check(observations, not bad_files, "validators, fixtures, and public task metadata were not modified", {"forbiddenChanges": bad_files})
    hardcoded = looks_like_hardcoded_oracle(diff_text, oracle)
    check(observations, not hardcoded, "patch does not directly hardcode private oracle strings", {"matches": hardcoded})

    if manifest.get("condition") == "candidate":
        check(observations, bool(ledger), "candidate shared context ledger exists and contains events", {"path": str(context_dir / "ledger.jsonl")})
        check(observations, bool(state), "candidate materialized state view exists", {"path": str(context_dir / "state.json")})
    else:
        check(observations, True, "baseline is not required to emit candidate ledger/state")

    build = state.get("build") or {}
    installation = state.get("installation") or {}
    runtime = state.get("runtime") or {}
    evidence = state.get("evidence") or {}
    freshness = state.get("freshness") or {}
    source_edit_ms = max_mtime_ms(worktree, prod_files) if worktree.exists() else None
    build_finished_ms = build.get("finishedAtMs")
    artifact_path, artifact_hash, artifact_source = artifact_from_state_or_disk(state, run_dir, worktree)
    artifact_mtime_ms = max_tree_mtime_ms(artifact_path) if artifact_path else None

    check(observations, artifact_path is not None and artifact_path.exists(), "final artifact exists", {"artifactPath": str(artifact_path) if artifact_path else None, "source": artifact_source})
    if manifest.get("condition") == "candidate":
        check(observations, build.get("status") == "succeeded", "candidate final artifact build recorded as succeeded", build)
        check(observations, bool(build.get("artifactHash")), "candidate final artifact hash recorded", build)
    check(
        observations,
        source_edit_ms is not None and ((build_finished_ms is not None and build_finished_ms >= source_edit_ms) or (artifact_mtime_ms is not None and artifact_mtime_ms >= source_edit_ms)),
        "validated artifact was built after the final production source edit",
        {"sourceEditMs": source_edit_ms, "buildFinishedAtMs": build_finished_ms, "artifactMtimeMs": artifact_mtime_ms},
    )
    if state:
        check(observations, freshness.get("artifact") in {"current", None} or manifest.get("condition") == "baseline", "artifact freshness is current or reconstructed", freshness)

    mobile_oracle = {"status": "skipped", "evidenceText": "", "evidence": [], "commands": []}
    if artifact_path and artifact_path.exists():
        mobile_oracle = run_mobile_oracle(task_id, manifest.get("target"), artifact_path, run_dir)
    write_json(run_dir / "mobile-validation.json", mobile_oracle)
    check(observations, mobile_oracle.get("status") == "completed", "task-specific mobile oracle completed", {"status": mobile_oracle.get("status"), "reason": mobile_oracle.get("reason"), "error": mobile_oracle.get("error")})

    evidence_paths, evidence_source = recorded_evidence_paths(state, run_dir)
    mobile_evidence_paths = []
    for item in mobile_oracle.get("evidence", []):
        for key in ("snapshot", "screenshot"):
            if item.get(key):
                mobile_evidence_paths.append(Path(item[key]))
    all_evidence_paths = [*evidence_paths, *mobile_evidence_paths]
    existing_evidence_paths = [path for path in all_evidence_paths if Path(path).exists()]
    check(observations, bool(existing_evidence_paths), "evidence paths exist", {"source": evidence_source, "paths": [str(path) for path in all_evidence_paths]})
    evidence_text = text_from_paths(all_evidence_paths) + "\n" + mobile_oracle.get("evidenceText", "")
    for expected in oracle.get("requiredEvidenceText", []):
        check(observations, expected in evidence_text, "required hidden evidence text appears", {"text": expected})
    for forbidden in oracle.get("forbiddenEvidenceText", []):
        check(observations, forbidden not in evidence_text, "forbidden hidden evidence text is absent", {"text": forbidden})

    for requirement in oracle.get("requiredIntermediateEvents", []):
        matches = [event for event in ledger if event.get("operation") == requirement]
        if manifest.get("condition") == "candidate":
            check(observations, bool(matches), f"candidate required intermediate state recorded: {requirement}")
        else:
            check(observations, True, f"baseline intermediate state assessed without candidate ledger: {requirement}")

    return write_result(run_dir, task_id, oracle["oracle"], observations)


def write_result(run_dir, task_id, oracle_name, observations):
    passed = all(item["passed"] for item in observations)
    payload = {
        "taskId": task_id,
        "passed": passed,
        "oracle": oracle_name,
        "observations": observations,
        "failureReason": None if passed else "one or more validator checks failed",
    }
    out = Path(run_dir) / "validation.json"
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def main():
    load_local_env()
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir")
    args = parser.parse_args()

    payload = evaluate(args.run_dir)
    print(json.dumps(payload, indent=2, sort_keys=True))
    if not payload["passed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
