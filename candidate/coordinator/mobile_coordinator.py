#!/usr/bin/env python3
import argparse
import json
import sys
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


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


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


def preflight_manifest(args):
    return {
        "schemaVersion": 1,
        "runDir": str(args.run_dir),
        "runId": args.run_dir.name,
        "condition": args.condition,
        "taskId": args.task_id,
        "preflight": {
            "source": {
                "head": args.source_head,
                "present": bool(args.source_head),
            },
            "expected": {
                "target": args.target,
                "fixture": args.fixture,
                "fault": args.fault,
            },
            "identityChecks": {
                "conditionIsCandidate": args.condition == "candidate",
                "taskIdPresent": bool(args.task_id),
                "targetPresent": bool(args.target),
                "fixturePresent": bool(args.fixture),
                "sourceHeadPresent": bool(args.source_head),
            },
            "existingState": {
                "artifact": None,
                "runtime": None,
                "evidence": None,
            },
            "health": "not-started",
            "recommendedTransition": "rebuild",
            "toolLock": json.loads(args.tool_lock_json),
            "limits": json.loads(args.limits_json),
        },
    }


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


def merge_postflight(args):
    existing = load_json(args.output)
    postflight = inspect_run(args.run_dir)
    expected = existing.get("preflight", {}).get("expected", {})
    actual_task_id = postflight.get("taskId")
    actual_target = postflight.get("runtime", {}).get("target")
    postflight["identityChecks"] = {
        "taskIdMatches": actual_task_id == existing.get("taskId"),
        "targetMatches": actual_target == expected.get("target"),
        "sourceHeadMatches": postflight.get("source", {}).get("head") == existing.get("preflight", {}).get("source", {}).get("head"),
    }
    existing["postflight"] = postflight
    return existing


def main():
    if len(sys.argv) > 1 and sys.argv[1] not in {"preflight", "postflight", "inspect", "-h", "--help"}:
        sys.argv.insert(1, "inspect")

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")

    preflight = subparsers.add_parser("preflight")
    preflight.add_argument("run_dir", type=Path)
    preflight.add_argument("--output", type=Path, required=True)
    preflight.add_argument("--condition", required=True)
    preflight.add_argument("--task-id", required=True)
    preflight.add_argument("--target", required=True)
    preflight.add_argument("--fixture", required=True)
    preflight.add_argument("--fault", required=True)
    preflight.add_argument("--source-head", required=True)
    preflight.add_argument("--tool-lock-json", required=True)
    preflight.add_argument("--limits-json", required=True)

    postflight = subparsers.add_parser("postflight")
    postflight.add_argument("run_dir", type=Path)
    postflight.add_argument("--output", type=Path, required=True)

    inspect = subparsers.add_parser("inspect")
    inspect.add_argument("run_dir", type=Path)
    inspect.add_argument("--output", type=Path)
    args = parser.parse_args()

    if args.command == "preflight":
        payload = preflight_manifest(args)
        write_json(args.output, payload)
        print(args.output)
        return
    if args.command == "postflight":
        payload = merge_postflight(args)
        write_json(args.output, payload)
        print(args.output)
        return

    run_dir = args.run_dir
    output = args.output
    payload = inspect_run(run_dir)
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if output:
        write_json(output, payload)
        print(output)
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
