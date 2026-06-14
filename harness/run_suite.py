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

from evaluate_run import evaluate
from metrics import flatten, load_json


ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs"
TASKS = ROOT / "experiment" / "public" / "tasks.json"
LIMITS = ROOT / "experiment" / "public" / "limits.json"
DEFAULT_SUITE = ROOT / "experiment" / "public" / "suites" / "clean-controls.json"


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


def run_task(task_id, condition, args, timeout):
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
    proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, timeout=timeout)
    duration = round(time.time() - started, 3)
    manifest_path = None
    for line in reversed(proc.stdout.splitlines()):
        candidate = Path(line.strip())
        if candidate.exists() and candidate.name == "manifest.json":
            manifest_path = candidate
            break
    return proc, duration, manifest_path


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
    has_candidate = any(run["condition"] == "candidate" for run in runs)
    if has_candidate and not allow_candidate:
        raise SystemExit(
            "candidate runs are reserved until the coordinator is implemented; "
            "use --plan-only to inspect randomized comparison plans"
        )


def actual_outcome(exit_code, validation_passed):
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


def summarize_suite(suite_id, suite_dir, suite, known_tasks, run_results):
    rows = []
    passed = 0
    completed = 0
    expected_matched = 0
    for item in run_results:
        metrics = load_json(Path(item["runDir"]) / "metrics.json") if item.get("runDir") else {}
        validation = load_json(Path(item["runDir"]) / "validation.json") if item.get("runDir") else {}
        flat_metrics = flatten(metrics) if metrics else {}
        task = known_tasks[item["taskId"]]
        expected = task_expected_outcome(task, suite, item["condition"])
        validation_passed = validation.get("passed")
        actual = actual_outcome(item.get("exitCode"), validation_passed)
        outcome_matched = actual == expected
        row = {
            **item,
            **flat_metrics,
            "expectedOutcome": expected,
            "actualOutcome": actual,
            "outcomeMatched": outcome_matched,
            "validationPassed": validation_passed,
        }
        rows.append(row)
        completed += int(item.get("exitCode") == 0)
        passed += int(validation_passed is True)
        expected_matched += int(outcome_matched)

    payload = {
        "suiteId": suite_id,
        "suiteDir": str(suite_dir),
        "totalRuns": len(run_results),
        "completedRuns": completed,
        "validatedRuns": passed,
        "expectedOutcomeMatchedRuns": expected_matched,
        "allCompleted": completed == len(run_results),
        "allValidated": passed == len(run_results),
        "allExpectedOutcomesMatched": expected_matched == len(run_results),
        "runs": rows,
    }
    write_json(suite_dir / "suite-summary.json", payload)
    return payload


def main():
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
        "candidateExecutionAllowed": args.allow_candidate,
        "executeAgent": args.execute_agent,
        "evaluate": not args.no_evaluate,
    })
    print(suite_dir / "suite-plan.json")
    if args.plan_only:
        return

    results = []
    for index, run_spec in enumerate(runs, start=1):
        proc, duration, manifest_path = run_task(run_spec["taskId"], run_spec["condition"], args, timeout)
        run_dir = manifest_path.parent if manifest_path else None
        validation = None
        if proc.returncode == 0 and run_dir and not args.no_evaluate:
            validation = evaluate(run_dir)
        expected = task_expected_outcome(known_tasks[run_spec["taskId"]], suite, run_spec["condition"])
        validation_passed = validation.get("passed") if validation else None
        actual = actual_outcome(proc.returncode, validation_passed)
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
            "validationPassed": validation_passed,
        }
        append_jsonl(suite_dir / "suite-runs.jsonl", result)
        results.append(result)
        print(json.dumps(result, sort_keys=True))

        if not outcome_matched and not args.keep_going:
            break

    summary = summarize_suite(suite_id, suite_dir, suite, known_tasks, results)
    print(suite_dir / "suite-summary.json")
    if not summary["allExpectedOutcomesMatched"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
