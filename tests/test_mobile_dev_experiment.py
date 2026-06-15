import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHONPATH = str(ROOT / "candidate")


def run_mobile_dev(args, context_dir, check=True):
    env = os.environ.copy()
    env["PYTHONPATH"] = PYTHONPATH
    env["LOOPLAB_RUN_CONTEXT_DIR"] = str(context_dir)
    proc = subprocess.run(
        [sys.executable, "-m", "mobile_dev.cli", *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if check and proc.returncode != 0:
        raise AssertionError(proc.stderr or proc.stdout)
    return proc


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


class MobileDevExperimentTests(unittest.TestCase):
    def test_normalized_run_preserves_raw_output_and_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = Path(tmp)
            proc = run_mobile_dev(
                ["run", "--operation", "install", "--provider", "fake-provider", "--", sys.executable, "-c", "print('raw ok')"],
                ctx,
            )
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["operation"], "install")
            self.assertEqual(payload["provider"], "fake-provider")
            self.assertEqual(payload["status"], "succeeded")
            self.assertEqual(payload["providerCode"], "0")
            self.assertTrue(Path(payload["rawOutputPath"]).is_file())
            self.assertIn("raw ok", Path(payload["rawOutputPath"]).read_text(encoding="utf-8"))
            self.assertEqual(len(load_jsonl(ctx / "ledger.jsonl")), 1)
            self.assertEqual(load_json(ctx / "state.json")["counts"]["events"], 1)

    def test_unknown_state_is_not_inferred(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = Path(tmp)
            proc = run_mobile_dev(["status"], ctx)
            state = json.loads(proc.stdout)
            self.assertEqual(state["freshness"]["artifact"], "unknown")
            self.assertIsNone(state["build"])
            self.assertEqual(state["counts"]["events"], 0)

    def test_source_change_invalidates_later_relationships(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = Path(tmp)
            artifact = ctx / "LoopLab.app"
            artifact.mkdir()
            (artifact / "LoopLab").write_text("binary", encoding="utf-8")
            run_mobile_dev(["record", "source", "--source-state-hash", "source-a"], ctx)
            run_mobile_dev(["record", "build", "--artifact-path", str(artifact), "--source-state-hash", "source-a"], ctx)
            state = load_json(ctx / "state.json")
            self.assertEqual(state["freshness"]["artifact"], "current")
            run_mobile_dev(["record", "source", "--source-state-hash", "source-b"], ctx)
            state = load_json(ctx / "state.json")
            self.assertEqual(state["freshness"]["artifact"], "stale")

    def test_candidate_cli_has_no_validate_or_workflow_command(self):
        proc = subprocess.run(
            [str(ROOT / "candidate" / "bin" / "mobile-dev"), "--help"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertNotIn("validate", proc.stdout)
        self.assertFalse((ROOT / "candidate" / "bin" / "mobile-loop").exists())

    def test_baseline_candidate_isolation_and_no_candidate_recovery(self):
        run_task = (ROOT / "harness" / "run_task.py").read_text(encoding="utf-8")
        self.assertIn('condition == "baseline"', run_task)
        self.assertIn("candidate_assets_removed", run_task)
        self.assertNotIn("coordinator_recover", run_task)
        self.assertNotIn("relaunch-after-runtime-recovery", run_task)
        self.assertNotIn("recover-backend", run_task)

    def test_limits_and_oracle_requirements_are_declared(self):
        limits = load_json(ROOT / "experiment" / "public" / "limits.json")
        self.assertEqual(limits["processTimeoutSeconds"], 600)
        self.assertEqual(limits["maxTurns"], 20)
        self.assertEqual(limits["maxToolCalls"], 100)
        self.assertNotIn("maxCostUsd", limits)

        oracles = load_json(ROOT / "experiment" / "private" / "validators" / "task_oracles.json")["tasks"]
        self.assertEqual(len(oracles), 8)
        for oracle in oracles.values():
            self.assertTrue(oracle["initialOracleExpectedFailure"])
            self.assertIn("source", oracle["requiredIntermediateEvents"])
            self.assertIn("build", oracle["requiredIntermediateEvents"])
            self.assertIn("evidence", oracle["requiredIntermediateEvents"])

        evaluator = (ROOT / "harness" / "evaluate_run.py").read_text(encoding="utf-8")
        self.assertIn("production source code changed", evaluator)
        self.assertIn("validated artifact was built after the final production source edit", evaluator)
        self.assertIn("evidence remains current to runtime", evaluator)


if __name__ == "__main__":
    unittest.main()
