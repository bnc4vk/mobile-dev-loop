#!/usr/bin/env python3
import argparse
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ORACLES = ROOT / "experiment" / "private" / "validators" / "task_oracles.json"


def load_json(path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


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

    check(observations, bool(ledger), "shared context ledger exists and contains events", {"path": str(context_dir / "ledger.jsonl")})
    check(observations, bool(state), "materialized state view exists", {"path": str(context_dir / "state.json")})

    build = state.get("build") or {}
    installation = state.get("installation") or {}
    runtime = state.get("runtime") or {}
    evidence = state.get("evidence") or {}
    freshness = state.get("freshness") or {}
    source_edit_ms = max_mtime_ms(worktree, prod_files) if worktree.exists() else None
    build_finished_ms = build.get("finishedAtMs")

    check(observations, build.get("status") == "succeeded", "final artifact build succeeded", build)
    check(observations, bool(build.get("artifactHash")), "final artifact hash recorded", build)
    check(
        observations,
        source_edit_ms is not None and build_finished_ms is not None and build_finished_ms >= source_edit_ms,
        "validated artifact was built after the final production source edit",
        {"sourceEditMs": source_edit_ms, "buildFinishedAtMs": build_finished_ms},
    )
    check(observations, freshness.get("artifact") == "current", "artifact remains current to source", freshness)
    check(observations, installation.get("status") == "succeeded", "installation succeeded", installation)
    check(observations, runtime.get("status") == "succeeded", "runtime launch/session succeeded", runtime)
    check(observations, evidence.get("status") == "succeeded", "final evidence capture succeeded", evidence)
    check(observations, freshness.get("installation") == "current", "installation remains current to artifact", freshness)
    check(observations, freshness.get("runtime") == "current", "runtime remains current to installation", freshness)
    check(observations, freshness.get("evidence") == "current", "evidence remains current to runtime", freshness)

    evidence_paths = evidence.get("paths") or []
    existing_evidence_paths = [path for path in evidence_paths if Path(path).exists()]
    check(observations, len(existing_evidence_paths) == len(evidence_paths) and bool(evidence_paths), "all recorded evidence paths exist", {"paths": evidence_paths})
    evidence_text = text_from_paths(evidence_paths)
    for expected in oracle.get("requiredEvidenceText", []):
        check(observations, expected in evidence_text, "required hidden evidence text appears", {"text": expected})
    for forbidden in oracle.get("forbiddenEvidenceText", []):
        check(observations, forbidden not in evidence_text, "forbidden hidden evidence text is absent", {"text": forbidden})

    for requirement in oracle.get("requiredIntermediateEvents", []):
        matches = [event for event in ledger if event.get("operation") == requirement]
        check(observations, bool(matches), f"required intermediate state recorded: {requirement}")

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
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir")
    args = parser.parse_args()

    payload = evaluate(args.run_dir)
    print(json.dumps(payload, indent=2, sort_keys=True))
    if not payload["passed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
