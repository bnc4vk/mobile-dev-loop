#!/usr/bin/env python3
import argparse
import json
import statistics
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs"
DEFAULT_SUITE_PREFIXES = [
    "pilot-eight-task-comparison",
]


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def latest_suite_summary(prefix):
    candidates = sorted(
        (path for path in (RUNS / "suites").glob(f"{prefix}-*/suite-summary.json")),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise SystemExit(f"no suite summary found for {prefix}")
    return candidates[0]


def default_summaries():
    return [latest_suite_summary(prefix) for prefix in DEFAULT_SUITE_PREFIXES]


def mean(values):
    values = [value for value in values if isinstance(value, (int, float))]
    return round(statistics.mean(values), 3) if values else None


def suite_rows(summaries):
    rows = []
    for path, summary in summaries:
        rows.append({
            "suiteId": summary["suiteId"],
            "summaryPath": str(path),
            "totalRuns": summary["totalRuns"],
            "expectedOutcomeMatchedRuns": summary.get("expectedOutcomeMatchedRuns"),
            "allExpectedOutcomesMatched": summary.get("allExpectedOutcomesMatched"),
            "oraclePassRuns": sum(1 for run in summary["runs"] if run.get("actualOutcome") == "oracle-pass"),
            "validationFailureRuns": sum(1 for run in summary["runs"] if run.get("actualOutcome") == "validation-failure"),
            "processFailureRuns": sum(1 for run in summary["runs"] if run.get("actualOutcome") == "process-failure"),
            "invalidCensoredRuns": sum(1 for run in summary["runs"] if run.get("actualOutcome") == "invalid-censored"),
            "meanSeconds": mean(run.get("totalSeconds") for run in summary["runs"]),
        })
    return rows


def task_rows(summaries):
    rows = []
    for _, summary in summaries:
        for run in summary["runs"]:
            rows.append({
                "suiteId": summary["suiteId"],
                "taskId": run.get("taskId"),
                "target": run.get("target"),
                "fault": run.get("fault"),
                "expectedOutcome": run.get("expectedOutcome"),
                "actualOutcome": run.get("actualOutcome"),
                "outcomeMatched": run.get("outcomeMatched"),
                "validationPassed": run.get("validationPassed"),
                "provenSourceArtifactRuntimeEvidence": run.get("provenSourceArtifactRuntimeEvidence"),
                "evidenceCompleteness": run.get("evidenceCompleteness"),
                "buildCount": run.get("buildCount"),
                "installCount": run.get("installCount"),
                "failureCount": run.get("failureCount"),
                "totalSeconds": run.get("totalSeconds"),
                "runDir": run.get("runDir"),
            })
    return rows


def markdown_table(headers, rows):
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(header, "")) for header in headers) + " |")
    return "\n".join(lines)


def write_report(out_dir, suite_data):
    suites = suite_rows(suite_data)
    tasks = task_rows(suite_data)
    payload = {
        "suites": suites,
        "tasks": tasks,
        "allExpectedOutcomesMatched": all(row["allExpectedOutcomesMatched"] for row in suites),
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "baseline-report.json"
    md_path = out_dir / "baseline-report.md"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    suite_headers = [
        "suiteId",
        "totalRuns",
        "expectedOutcomeMatchedRuns",
        "allExpectedOutcomesMatched",
        "oraclePassRuns",
        "validationFailureRuns",
        "processFailureRuns",
        "invalidCensoredRuns",
        "meanSeconds",
    ]
    task_headers = [
        "taskId",
        "target",
        "fault",
        "expectedOutcome",
        "actualOutcome",
        "outcomeMatched",
        "provenSourceArtifactRuntimeEvidence",
        "evidenceCompleteness",
        "failureCount",
        "totalSeconds",
    ]
    md_path.write_text(
        "\n".join([
            "# Baseline Pilot Report",
            "",
            f"All expected outcomes matched: {payload['allExpectedOutcomesMatched']}",
            "",
            "## Suites",
            "",
            markdown_table(suite_headers, suites),
            "",
            "## Runs",
            "",
            markdown_table(task_headers, tasks),
            "",
        ]),
        encoding="utf-8",
    )
    return json_path, md_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("summaries", nargs="*", type=Path)
    parser.add_argument("--out-dir", type=Path)
    args = parser.parse_args()

    summary_paths = args.summaries or default_summaries()
    suite_data = [(path, load_json(path)) for path in summary_paths]
    out_dir = args.out_dir or RUNS / "reports" / f"baseline-{uuid.uuid4().hex[:10]}"
    json_path, md_path = write_report(out_dir, suite_data)
    print(json_path)
    print(md_path)


if __name__ == "__main__":
    main()
