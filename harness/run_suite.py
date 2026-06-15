#!/usr/bin/env python3
import argparse
import json
import os
import random
import subprocess
import sys
import time
import uuid
from pathlib import Path

from local_config import load_local_env

from agent_device_cleanup import terminate_repo_agent_device_daemons
from evaluate_run import evaluate
from metrics import flatten, load_json


ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs"
TASKS = ROOT / "experiment" / "public" / "tasks.json"
LIMITS = ROOT / "experiment" / "public" / "limits.json"
DEFAULT_SUITE = ROOT / "experiment" / "public" / "suites" / "pilot-eight-task-comparison.json"


def print_json(payload):
    print(json.dumps(payload, sort_keys=True), flush=True)


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def append_jsonl(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def load_tasks():
    tasks = json.loads(TASKS.read_text(encoding="utf-8"))["tasks"]
    return {task["id"]: task for task in tasks}


def load_suite(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def run_prefix(task_id, condition):
    return f"{task_id}-{condition}-"


def discover_run_dir(task_id, condition, started):
    candidates = [
        path
        for path in RUNS.glob(f"{run_prefix(task_id, condition)}*")
        if path.is_dir() and path.stat().st_mtime >= started - 1
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def latest_telemetry_event(run_dir):
    if not run_dir:
        return None
    telemetry = run_dir / "telemetry.jsonl"
    if not telemetry.exists():
        return None
    try:
        lines = [line for line in telemetry.read_text(encoding="utf-8").splitlines() if line.strip()]
    except OSError:
        return None
    if not lines:
        return None
    try:
        event = json.loads(lines[-1])
    except json.JSONDecodeError:
        return None
    return {
        "event": event.get("event"),
        "tsMs": event.get("tsMs"),
        "command": event.get("command"),
        "tool": event.get("tool"),
    }


def summarize_text(value, limit=500):
    if not value:
        return None
    text = " ".join(str(value).split())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "..."


def latest_codex_event(run_dir):
    if not run_dir:
        return None
    events_path = run_dir / "codex-events.jsonl"
    if not events_path.exists():
        return None
    try:
        lines = [line for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except OSError:
        return None
    for line in reversed(lines):
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        item = event.get("item") or {}
        summary = {
            "type": event.get("type"),
            "itemType": item.get("type"),
            "status": item.get("status"),
        }
        if item.get("type") == "command_execution":
            summary["command"] = summarize_text(item.get("command"), limit=300)
            summary["exitCode"] = item.get("exit_code")
            summary["outputTail"] = summarize_text(item.get("aggregated_output"), limit=500)
        elif item.get("type") == "agent_message":
            summary["text"] = summarize_text(item.get("text"), limit=500)
        elif item:
            summary["id"] = item.get("id")
        return {key: value for key, value in summary.items() if value is not None}
    return None


def emit_agent_device_cleanup(args, phase, suite_id=None, suite_index=None, total_runs=None, task_id=None, condition=None):
    if args.no_agent_device_cleanup:
        return None
    cleanup = terminate_repo_agent_device_daemons()
    print_json({
        "event": "agent_device_cleanup",
        "suiteId": suite_id,
        "suiteIndex": suite_index,
        "totalRuns": total_runs,
        "taskId": task_id,
        "condition": condition,
        "phase": phase,
        "terminated": len(cleanup["terminated"]),
        "killed": len(cleanup["killed"]),
        "remaining": len(cleanup["remaining"]),
    })
    return cleanup


def run_task(task_id, condition, args, timeout, suite_id=None, suite_index=None, total_runs=None):
    cmd = [
        sys.executable,
        str(ROOT / "harness" / "run_task.py"),
        "--task",
        task_id,
        "--condition",
        condition,
    ]
    if args.execute_agent:
        cmd.append("--execute-agent")
    if condition == "candidate" and args.allow_candidate:
        cmd.append("--allow-candidate")
    if args.device_id:
        cmd += ["--device-id", args.device_id]
    if args.development_team:
        cmd += ["--development-team", args.development_team]

    started = time.time()
    emit_agent_device_cleanup(args, "before_run", suite_id, suite_index, total_runs, task_id, condition)
    print_json({
        "event": "run_started",
        "suiteId": suite_id,
        "suiteIndex": suite_index,
        "totalRuns": total_runs,
        "taskId": task_id,
        "condition": condition,
        "executeAgent": args.execute_agent,
    })
    proc = subprocess.Popen(cmd, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout = ""
    stderr = ""
    heartbeat_seconds = max(1, int(args.heartbeat_seconds))
    while True:
        try:
            out, err = proc.communicate(timeout=heartbeat_seconds)
            stdout += out or ""
            stderr += err or ""
            break
        except subprocess.TimeoutExpired:
            elapsed = round(time.time() - started, 3)
            if elapsed > timeout:
                proc.kill()
                out, err = proc.communicate()
                stdout += out or ""
                stderr += err or ""
                emit_agent_device_cleanup(args, "after_timeout", suite_id, suite_index, total_runs, task_id, condition)
                raise subprocess.TimeoutExpired(cmd, timeout, output=stdout, stderr=stderr)
            run_dir = discover_run_dir(task_id, condition, started)
            print_json({
                "event": "run_heartbeat",
                "suiteId": suite_id,
                "suiteIndex": suite_index,
                "totalRuns": total_runs,
                "taskId": task_id,
                "condition": condition,
                "elapsedSeconds": elapsed,
                "runDir": str(run_dir) if run_dir else None,
                "latestTelemetry": latest_telemetry_event(run_dir),
                "latestCodexEvent": latest_codex_event(run_dir),
            })
    duration = round(time.time() - started, 3)
    manifest_path = None
    for line in reversed(stdout.splitlines()):
        candidate = Path(line.strip())
        if candidate.exists() and candidate.name == "manifest.json":
            manifest_path = candidate
            break
    completed = subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)
    emit_agent_device_cleanup(args, "after_run", suite_id, suite_index, total_runs, task_id, condition)
    return completed, duration, manifest_path


def planned_runs(suite, args):
    if args.condition:
        conditions = args.condition
    elif "conditions" in suite:
        conditions = suite["conditions"]
    else:
        conditions = [suite.get("condition") or "baseline"]
    if isinstance(conditions, str):
        conditions = [conditions]

    runs_per_task = args.runs_per_task or int(suite.get("runsPerTask", 1))
    task_ids = args.task or suite.get("tasks", [])
    runs = [
        {"taskId": task_id, "condition": condition, "runOrdinal": run_ordinal}
        for task_id in task_ids
        for condition in conditions
        for run_ordinal in range(1, runs_per_task + 1)
    ]
    should_shuffle = args.shuffle or bool(suite.get("shuffle", False))
    seed = args.seed if args.seed is not None else int(suite.get("seed", 1))
    if should_shuffle:
        random.Random(seed).shuffle(runs)
    return runs


def assert_candidate_ready(runs, allow_candidate):
    return None


def actual_outcome(exit_code, validation_passed, metrics=None):
    secondary = metrics.get("secondary", {}) if metrics else {}
    if exit_code != 0 and secondary.get("meaningfulTaskExecution") is False:
        return "invalid-censored"
    if exit_code != 0:
        return "process-failure"
    if validation_passed is True:
        return "oracle-pass"
    if validation_passed is False:
        return "validation-failure"
    return "completed-unvalidated"


def task_expected_outcome(task, suite, condition):
    condition_overrides = suite.get("expectedOutcomesByCondition", {}).get(condition, {})
    if task["id"] in condition_overrides:
        return condition_overrides[task["id"]]
    condition_key = f"{condition}ExpectedOutcome"
    if condition_key in task:
        return task[condition_key]
    overrides = suite.get("expectedOutcomes", {})
    if task["id"] in overrides:
        return overrides[task["id"]]
    return task.get("expectedOutcome", "oracle-pass")


def limit_violations(metrics, limits):
    secondary = metrics.get("secondary", {}) if metrics else {}
    violations = []
    checks = [
        ("maxTurns", "turnCount"),
        ("maxToolCalls", "toolCallCount"),
    ]
    for limit_key, metric_key in checks:
        limit = limits.get(limit_key)
        value = secondary.get(metric_key)
        if limit is not None and value is not None and value > limit:
            violations.append({
                "limit": limit_key,
                "metric": metric_key,
                "value": value,
                "maximum": limit,
            })
    if secondary.get("processLimitHit"):
        violations.append({
            "limit": "processTimeoutSeconds",
            "metric": "processLimitHit",
            "value": True,
            "maximum": limits.get("processTimeoutSeconds"),
        })
    return violations


def summarize_suite(suite_id, suite_dir, suite, known_tasks, run_results):
    rows = []
    passed = 0
    completed = 0
    expected_matched = 0
    limits_respected = 0
    for item in run_results:
        metrics = load_json(Path(item["runDir"]) / "metrics.json") if item.get("runDir") else {}
        validation = load_json(Path(item["runDir"]) / "validation.json") if item.get("runDir") else {}
        flat_metrics = flatten(metrics) if metrics else {}
        task = known_tasks[item["taskId"]]
        expected = task_expected_outcome(task, suite, item["condition"])
        validation_passed = validation.get("passed")
        actual = actual_outcome(item.get("exitCode"), validation_passed, metrics)
        outcome_matched = actual == expected
        violations = item.get("limitViolations")
        if violations is None:
            violations = limit_violations(metrics, item.get("limits", {}))
        row = {
            **item,
            **flat_metrics,
            "expectedOutcome": expected,
            "actualOutcome": actual,
            "outcomeMatched": outcome_matched,
            "limitViolations": violations,
            "validationPassed": validation_passed,
        }
        rows.append(row)
        completed += int(item.get("exitCode") == 0)
        passed += int(validation_passed is True)
        expected_matched += int(outcome_matched)
        limits_respected += int(not violations)

    payload = {
        "suiteId": suite_id,
        "suiteDir": str(suite_dir),
        "totalRuns": len(run_results),
        "completedRuns": completed,
        "validatedRuns": passed,
        "expectedOutcomeMatchedRuns": expected_matched,
        "limitRespectedRuns": limits_respected,
        "allCompleted": completed == len(run_results),
        "allValidated": passed == len(run_results),
        "allExpectedOutcomesMatched": expected_matched == len(run_results),
        "allLimitsRespected": limits_respected == len(run_results),
        "runs": rows,
    }
    write_json(suite_dir / "suite-summary.json", payload)
    return payload


def main():
    load_local_env()
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    parser.add_argument("--condition", choices=["baseline", "candidate"], action="append")
    parser.add_argument("--task", action="append")
    parser.add_argument("--runs-per-task", type=int)
    parser.add_argument("--shuffle", action="store_true")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--allow-candidate", action="store_true")
    parser.add_argument("--execute-agent", action="store_true")
    parser.add_argument("--no-evaluate", action="store_true")
    parser.add_argument("--keep-going", action="store_true")
    parser.add_argument("--heartbeat-seconds", type=int, default=30)
    parser.add_argument("--no-agent-device-cleanup", action="store_true")
    parser.add_argument("--device-id", default=os.environ.get("LOOPLAB_DEVICE_ID"))
    parser.add_argument("--development-team", default=os.environ.get("LOOPLAB_DEVELOPMENT_TEAM"))
    args = parser.parse_args()

    suite = load_suite(args.suite)
    known_tasks = load_tasks()
    limits = json.loads(LIMITS.read_text(encoding="utf-8"))
    timeout = int(limits.get("processTimeoutSeconds", 7200))
    runs = planned_runs(suite, args)
    seed = args.seed if args.seed is not None else int(suite.get("seed", 1))
    should_shuffle = args.shuffle or bool(suite.get("shuffle", False))

    unknown = sorted({run["taskId"] for run in runs if run["taskId"] not in known_tasks})
    if unknown:
        raise SystemExit(f"unknown task ids in suite: {', '.join(unknown)}")
    if not args.plan_only:
        assert_candidate_ready(runs, args.allow_candidate)

    suite_id = f"{suite.get('id', args.suite.stem)}-{uuid.uuid4().hex[:10]}"
    suite_dir = RUNS / "suites" / suite_id
    write_json(suite_dir / "suite-plan.json", {
        "suiteId": suite_id,
        "suite": suite,
        "runs": runs,
        "limits": limits,
        "shuffle": should_shuffle,
        "seed": seed,
        "planOnly": args.plan_only,
        "candidateArmEnabled": True,
        "executeAgent": args.execute_agent,
        "evaluate": not args.no_evaluate,
    })
    print(suite_dir / "suite-plan.json", flush=True)
    if args.plan_only:
        return
    emit_agent_device_cleanup(args, "before_suite", suite_id=suite_id, total_runs=len(runs))

    results = []
    for index, run_spec in enumerate(runs, start=1):
        proc, duration, manifest_path = run_task(
            run_spec["taskId"],
            run_spec["condition"],
            args,
            timeout,
            suite_id=suite_id,
            suite_index=index,
            total_runs=len(runs),
        )
        run_dir = manifest_path.parent if manifest_path else None
        validation = None
        if proc.returncode == 0 and run_dir and not args.no_evaluate:
            validation_path = run_dir / "validation.json"
            validation = load_json(validation_path) if validation_path.exists() else evaluate(run_dir)
        metrics = load_json(run_dir / "metrics.json") if run_dir else {}
        violations = limit_violations(metrics, limits)
        expected = task_expected_outcome(known_tasks[run_spec["taskId"]], suite, run_spec["condition"])
        validation_passed = validation.get("passed") if validation else None
        actual = actual_outcome(proc.returncode, validation_passed, metrics)
        outcome_matched = actual == expected

        result = {
            **run_spec,
            "suiteId": suite_id,
            "suiteIndex": index,
            "exitCode": proc.returncode,
            "durationSeconds": duration,
            "runDir": str(run_dir) if run_dir else None,
            "manifestPath": str(manifest_path) if manifest_path else None,
            "stdoutTail": proc.stdout[-4000:],
            "stderrTail": proc.stderr[-4000:],
            "expectedOutcome": expected,
            "actualOutcome": actual,
            "outcomeMatched": outcome_matched,
            "limitViolations": violations,
            "limits": limits,
            "validationPassed": validation_passed,
        }
        append_jsonl(suite_dir / "suite-runs.jsonl", result)
        results.append(result)
        print_json({"event": "run_completed", **result})

        if (not outcome_matched or violations) and not args.keep_going:
            break

    summary = summarize_suite(suite_id, suite_dir, suite, known_tasks, results)
    print(suite_dir / "suite-summary.json", flush=True)
    if not summary["allExpectedOutcomesMatched"] or not summary["allLimitsRespected"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
