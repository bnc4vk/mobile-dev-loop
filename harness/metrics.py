#!/usr/bin/env python3
import argparse
import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs"


def load_jsonl(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_json(path):
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def command_label(command):
    joined = " ".join(command)
    if command[:2] == ["git", "worktree"]:
        return "worktree_create"
    if command and command[0] == "xcodebuild":
        return "build"
    if "simctl list" in joined:
        return "simulator_list"
    if "simctl boot " in joined:
        return "simulator_boot"
    if "simctl bootstatus" in joined:
        return "simulator_bootstatus"
    if "simctl install" in joined:
        return "install"
    if "simctl launch" in joined:
        return "launch"
    if "simctl terminate" in joined:
        return "terminate"
    if "devicectl device install app" in joined:
        return "install"
    if "devicectl device process launch" in joined:
        return "launch"
    if "devicectl device process terminate" in joined:
        return "terminate"
    if "agent-device" in joined and " prepare ios-runner " in joined:
        return "agent_device_prepare_ios_runner"
    if "agent-device" in joined and " open " in joined:
        return "agent_device_open"
    if "agent-device" in joined and " screenshot " in joined:
        return "agent_device_screenshot"
    if "agent-device" in joined and joined.endswith(" snapshot"):
        return "agent_device_snapshot"
    return None


def is_tolerated_failure(label, event):
    if label == "simulator_boot" and event.get("exitCode") != 0:
        stderr = event.get("stderr", "")
        stdout = event.get("stdout", "")
        text = f"{stdout}\n{stderr}".lower()
        return "already booted" in text or event.get("exitCode") == 149
    if label is None and event.get("command", [])[-1:] == ["close"] and event.get("exitCode") != 0:
        text = f"{event.get('stdout', '')}\n{event.get('stderr', '')}".lower()
        return "session_not_found" in text or "no active session" in text
    return False


def summarize_run(run_dir):
    run_dir = Path(run_dir)
    manifest = load_json(run_dir / "manifest.json")
    events = load_jsonl(run_dir / "telemetry.jsonl")
    by_event = {}
    for event in events:
        by_event.setdefault(event.get("event"), []).append(event)

    started = by_event.get("run_started", [{}])[0].get("tsMs")
    finished = by_event.get("run_finished", [{}])[0].get("tsMs")
    total_seconds = round((finished - started) / 1000, 3) if started and finished else None

    command_metrics = {}
    failed_commands = []
    command_timeouts = []
    for event in by_event.get("command_finished", []):
        command = event.get("command", [])
        label = command_label(command)
        tolerated = is_tolerated_failure(label, event)
        if label:
            bucket = command_metrics.setdefault(label, {"count": 0, "seconds": 0.0, "failures": 0})
            bucket["count"] += 1
            bucket["seconds"] = round(bucket["seconds"] + event.get("durationSeconds", 0), 3)
            if event.get("exitCode") != 0 and not tolerated:
                bucket["failures"] += 1
        if event.get("exitCode") != 0 and not tolerated:
            failed_commands.append({
                "command": command,
                "exitCode": event.get("exitCode"),
                "label": label,
            })

    for event in by_event.get("command_timeout", []):
        command_timeouts.append({
            "command": event.get("command", []),
            "timeoutSeconds": event.get("timeoutSeconds"),
        })

    artifact = by_event.get("artifact_built", [{}])[-1] if by_event.get("artifact_built") else {}
    launch = by_event.get("app_launched", [{}])[-1] if by_event.get("app_launched") else {}
    evidence = by_event.get("agent_device_evidence_captured", [{}])[-1] if by_event.get("agent_device_evidence_captured") else {}

    evidence_paths = {
        "screenshot": evidence.get("screenshot"),
        "snapshot": evidence.get("snapshot"),
    }
    extra_evidence = evidence.get("extraEvidence", [])
    evidence_exists = {
        key: bool(value and Path(value).exists())
        for key, value in evidence_paths.items()
    }
    extra_evidence_exists = [
        {
            **item,
            "screenshotExists": bool(item.get("screenshot") and Path(item["screenshot"]).exists()),
            "snapshotExists": bool(item.get("snapshot") and Path(item["snapshot"]).exists()),
        }
        for item in extra_evidence
    ]

    trustworthy_artifact_validation = bool(
        artifact.get("sha256")
        and launch.get("deviceId")
        and evidence.get("openExitCode") == 0
        and evidence.get("screenshotExitCode") == 0
        and evidence.get("snapshotExitCode") == 0
        and all(evidence_exists.values())
    )

    install_count = command_metrics.get("install", {}).get("count", 0)
    build_count = command_metrics.get("build", {}).get("count", 0)
    reset_count = sum(
        1
        for event in by_event.get("command_finished", [])
        if "simctl erase" in " ".join(event.get("command", []))
    )

    metrics = {
        "runId": manifest.get("runId") or run_dir.name,
        "taskId": manifest.get("task", {}).get("id"),
        "condition": manifest.get("condition"),
        "target": manifest.get("target"),
        "sourceHead": manifest.get("sourceHead"),
        "toolLock": manifest.get("toolLock", {}),
        "status": "completed" if finished else "failed" if by_event.get("run_failed") else "incomplete",
        "fault": manifest.get("task", {}).get("fault"),
        "totalSeconds": total_seconds,
        "artifact": {
            "path": artifact.get("path"),
            "sha256": artifact.get("sha256"),
            "platform": artifact.get("platform"),
        },
        "device": {
            "target": launch.get("target"),
            "id": launch.get("deviceId"),
            "name": launch.get("deviceName"),
        },
        "primary": {
            "trustworthyArtifactValidation": trustworthy_artifact_validation,
            "stateRestorationSuccess": None,
            "automaticEnvironmentRecoverySuccess": None,
            "wastedAgentIterationsCausedByInfrastructure": None,
            "editToTrustworthyObservationSeconds": total_seconds if trustworthy_artifact_validation else None,
            "unnecessaryBuildsReinstallsResets": None,
            "successfulSimulatorToDeviceEscalation": None,
            "finalTaskCompletion": None,
        },
        "secondary": {
            "tokenUsage": None,
            "turnCount": None,
            "toolCallCount": None,
            "processLimitHit": bool(command_timeouts),
            "buildCount": build_count,
            "installCount": install_count,
            "resetCount": reset_count,
            "signingInstallLaunchAutomationFailures": len(failed_commands),
            "evidenceCompleteness": all(evidence_exists.values()),
            "physicalDeviceStrain": None,
        },
        "commands": command_metrics,
        "failures": {
            "failedCommands": failed_commands,
            "commandTimeouts": command_timeouts,
        },
        "evidence": {
            "paths": evidence_paths,
            "exists": evidence_exists,
            "extra": extra_evidence_exists,
            "agentDeviceStateDir": evidence.get("stateDir"),
        },
    }
    return metrics


def write_metrics(run_dir):
    run_dir = Path(run_dir)
    metrics = summarize_run(run_dir)
    out = run_dir / "metrics.json"
    out.write_text(json.dumps(metrics, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return metrics, out


def flatten(metrics):
    primary = metrics.get("primary", {})
    secondary = metrics.get("secondary", {})
    artifact = metrics.get("artifact", {})
    device = metrics.get("device", {})
    return {
        "runId": metrics.get("runId"),
        "taskId": metrics.get("taskId"),
        "condition": metrics.get("condition"),
        "target": metrics.get("target"),
        "fault": metrics.get("fault"),
        "status": metrics.get("status"),
        "totalSeconds": metrics.get("totalSeconds"),
        "artifactSha256": artifact.get("sha256"),
        "deviceId": device.get("id"),
        "trustworthyArtifactValidation": primary.get("trustworthyArtifactValidation"),
        "editToTrustworthyObservationSeconds": primary.get("editToTrustworthyObservationSeconds"),
        "buildCount": secondary.get("buildCount"),
        "installCount": secondary.get("installCount"),
        "resetCount": secondary.get("resetCount"),
        "evidenceCompleteness": secondary.get("evidenceCompleteness"),
        "failureCount": secondary.get("signingInstallLaunchAutomationFailures"),
        "processLimitHit": secondary.get("processLimitHit"),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dirs", nargs="*", help="Run directories to summarize. Defaults to all runs with telemetry.")
    parser.add_argument("--jsonl", type=Path)
    parser.add_argument("--csv", type=Path)
    args = parser.parse_args()

    if args.run_dirs:
        run_dirs = [Path(path) for path in args.run_dirs]
    else:
        run_dirs = sorted(path for path in RUNS.iterdir() if (path / "telemetry.jsonl").exists())

    all_metrics = []
    for run_dir in run_dirs:
        metrics, out = write_metrics(run_dir)
        all_metrics.append(metrics)
        print(out)

    if args.jsonl:
        args.jsonl.parent.mkdir(parents=True, exist_ok=True)
        args.jsonl.write_text("\n".join(json.dumps(metric, sort_keys=True) for metric in all_metrics) + "\n", encoding="utf-8")

    if args.csv:
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        rows = [flatten(metric) for metric in all_metrics]
        with args.csv.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()) if rows else [])
            writer.writeheader()
            writer.writerows(rows)


if __name__ == "__main__":
    main()
