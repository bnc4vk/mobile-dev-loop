#!/usr/bin/env python3
import argparse
import json
from pathlib import Path


def load_json(path):
    path = Path(path)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path):
    path = Path(path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def latest(events, name):
    matches = [event for event in events if event.get("event") == name]
    return matches[-1] if matches else {}


def command_failures(metrics):
    return metrics.get("failures", {}).get("failedCommands", [])


def runtime_health(metrics):
    evidence = metrics.get("evidence", {})
    failures = command_failures(metrics)
    if metrics.get("status") != "completed":
        return "process-failed"
    if not evidence.get("exists", {}).get("snapshot") or not evidence.get("exists", {}).get("screenshot"):
        return "evidence-missing"
    if metrics.get("primary", {}).get("trustworthyArtifactValidation") is not True:
        return "untrusted-observation"
    if failures:
        return "degraded"
    return "healthy"


def recommended_transition(metrics):
    health = runtime_health(metrics)
    failed_labels = {item.get("label") for item in command_failures(metrics)}
    if health == "healthy":
        return "reuse-observation"
    if "install" in failed_labels:
        return "rebuild"
    if "launch" in failed_labels:
        return "reinstall"
    if "agent_device_prepare_ios_runner" in failed_labels:
        return "reset"
    if health in {"evidence-missing", "untrusted-observation", "degraded"}:
        return "relaunch"
    return "rebuild"


def inspect_run(run_dir):
    run_dir = Path(run_dir)
    manifest = load_json(run_dir / "manifest.json")
    metrics = load_json(run_dir / "metrics.json")
    events = load_jsonl(run_dir / "telemetry.jsonl")
    backend = latest(events, "backend_started")
    launch = latest(events, "app_launched")
    evidence = latest(events, "agent_device_evidence_captured")
    return {
        "schemaVersion": 1,
        "runDir": str(run_dir),
        "runId": manifest.get("runId") or run_dir.name,
        "condition": manifest.get("condition"),
        "taskId": manifest.get("task", {}).get("id"),
        "source": {
            "head": manifest.get("sourceHead"),
        },
        "artifact": metrics.get("artifact", {}),
        "runtime": {
            "target": metrics.get("target"),
            "device": metrics.get("device", {}),
            "bundleId": launch.get("bundleId"),
        },
        "backend": {
            "fixture": backend.get("fixture"),
            "failure": backend.get("failure"),
            "urlHost": backend.get("urlHost"),
            "port": backend.get("port"),
        },
        "evidence": {
            "paths": metrics.get("evidence", {}).get("paths", {}),
            "exists": metrics.get("evidence", {}).get("exists", {}),
            "openExitCode": evidence.get("openExitCode"),
            "screenshotExitCode": evidence.get("screenshotExitCode"),
            "snapshotExitCode": evidence.get("snapshotExitCode"),
        },
        "health": runtime_health(metrics),
        "recommendedTransition": recommended_transition(metrics),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    payload = inspect_run(args.run_dir)
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        print(args.output)
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
