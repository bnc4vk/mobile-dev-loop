#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ORACLES = ROOT / "experiment" / "private" / "validators" / "task_oracles.json"


def load_json(path):
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def check(condition, observations, message, details=None):
    observations.append({
        "passed": bool(condition),
        "message": message,
        **({"details": details} if details is not None else {}),
    })


def latest_event(events, event_name):
    matches = [event for event in events if event.get("event") == event_name]
    return matches[-1] if matches else {}


def evaluate(run_dir):
    run_dir = Path(run_dir)
    manifest = load_json(run_dir / "manifest.json")
    metrics = load_json(run_dir / "metrics.json")
    events = load_jsonl(run_dir / "telemetry.jsonl")
    oracle_set = load_json(ORACLES)

    observations = []
    check(manifest is not None, observations, "manifest.json exists")
    check(metrics is not None, observations, "metrics.json exists")
    check(bool(events), observations, "telemetry.jsonl contains events")
    check(oracle_set is not None, observations, "private oracle file exists")

    if not manifest or not metrics or not oracle_set:
        return result(run_dir, None, "unknown", observations)

    task = manifest.get("task", {})
    task_id = task.get("id") or metrics.get("taskId")
    oracle = oracle_set.get("tasks", {}).get(task_id)
    check(oracle is not None, observations, "oracle exists for task", {"taskId": task_id})
    if oracle is None:
        return result(run_dir, task_id, "missing-oracle", observations)

    check(metrics.get("status") == "completed", observations, "run completed", {"status": metrics.get("status")})
    check(metrics.get("target") == oracle["expectedTarget"], observations, "target matches oracle", {"actual": metrics.get("target"), "expected": oracle["expectedTarget"]})
    check(task.get("fixture") == oracle["expectedFixture"], observations, "fixture matches oracle", {"actual": task.get("fixture"), "expected": oracle["expectedFixture"]})
    check(bool(metrics.get("artifact", {}).get("sha256")), observations, "artifact hash recorded")
    check(metrics.get("primary", {}).get("trustworthyArtifactValidation") is True, observations, "trustworthy artifact validation passed")

    evidence = metrics.get("evidence", {})
    paths = evidence.get("paths", {})
    screenshot_path = Path(paths.get("screenshot") or "")
    snapshot_path = Path(paths.get("snapshot") or "")
    check(screenshot_path.exists(), observations, "screenshot evidence exists", {"path": str(screenshot_path)})
    check(snapshot_path.exists(), observations, "snapshot evidence exists", {"path": str(snapshot_path)})

    snapshot_text = snapshot_path.read_text(encoding="utf-8") if snapshot_path.exists() else ""
    for expected in oracle.get("requiredSnapshotText", []):
        check(expected in snapshot_text, observations, "required text appears in snapshot", {"text": expected})
    for forbidden in oracle.get("forbiddenSnapshotText", []):
        check(forbidden not in snapshot_text, observations, "forbidden text absent from snapshot", {"text": forbidden})

    artifact_event = latest_event(events, "artifact_built")
    backend_url = artifact_event.get("backendUrl", "")
    for forbidden in oracle.get("forbiddenBackendUrlText", []):
        check(forbidden not in backend_url, observations, "forbidden backend URL text absent", {"text": forbidden, "backendUrl": backend_url})

    return result(run_dir, task_id, oracle["oracle"], observations)


def result(run_dir, task_id, oracle_name, observations):
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
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir")
    args = parser.parse_args()

    payload = evaluate(args.run_dir)
    print(json.dumps(payload, indent=2, sort_keys=True))
    if not payload["passed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
