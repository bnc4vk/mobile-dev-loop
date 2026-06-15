# Next Baseline-Versus-Candidate Experiment

Date: 2026-06-15

## Architecture

The experiment has two arms:

- Baseline: Codex receives direct access to the existing mobile tools, a concise condition-neutral quickstart, run-local state isolation, and evidence-preservation instructions.
- Candidate: the same model, prompt, limits, hardware, quickstart, and tools, plus `mobile-dev`.

`mobile-dev` is a tool-agnostic normalization and persisted-state layer. It writes to the shared run context directory exposed as:

```bash
LOOPLAB_RUN_CONTEXT_DIR=/absolute/path/to/run-context
```

The context contains:

- `ledger.jsonl`: append-only normalized operation events.
- `state.json`: materialized current state and freshness view.
- `raw-output/`: preserved raw provider outputs referenced by ledger events.
- agent-created screenshots, snapshots, logs, and supporting evidence.

`mobile-dev` commands:

```bash
mobile-dev record source --repo .
mobile-dev record build --provider xcodebuild --status succeeded --artifact-path /path/LoopLab.app --command "xcodebuild ..."
mobile-dev record install --provider simctl --status succeeded --device-id <udid> --artifact-path /path/LoopLab.app
mobile-dev record launch --provider simctl --status succeeded --device-id <udid> --session-id <session> --bundle-id com.mobiledevloop.LoopLab
mobile-dev record backend --provider mock-backend --status succeeded --endpoint "$LOOPLAB_BACKEND_URL" --fixture-state observed
mobile-dev record evidence --provider agent-device --status succeeded --kind accessibility --path /path/snapshot.txt --path /path/screenshot.png
mobile-dev status
mobile-dev history
mobile-dev run --operation build --provider xcodebuild -- xcodebuild ...
```

`mobile-dev run` wraps exactly one provider command. It does not chain commands, validate tasks, choose actions, recover faults, restart backends, repair artifacts, remove leases, or know oracle-specific UI strings.

## Removed Behaviors

The old candidate `mobile-loop validate` workflow has been removed. The candidate no longer bundles backend startup, build, install, launch, observation, evidence capture, validation, transition recommendations, or recovery.

The harness no longer branches on candidate condition to:

- restore backend fixtures;
- retry failed installs;
- clear automation runner leases;
- relaunch killed runtimes;
- reuse/retry observations;
- repair corrupted artifacts.

Any recovery must come from Codex observing public signals and choosing its own next command.

## Task Corpus

The initial corpus has eight production-code tasks:

1. `T01-record-selection-persistence-simulator`
2. `T02-cold-start-deep-link-simulator`
3. `T03-foreground-data-refresh-simulator`
4. `T04-out-of-order-request-protection-simulator`
5. `T05-offline-cached-account-fallback-simulator`
6. `T06-settings-migration-app-update-simulator`
7. `T07-malformed-backend-recovery-simulator`
8. `T08-camera-permission-refresh-iphone`

Public prompts describe user-visible behavior and constraints only. Private validators require:

- locked starting revision declared as failing the hidden oracle;
- production app source changes;
- no validator, fixture, or task-metadata evasion;
- final artifact built after final source edit;
- installation/runtime/evidence relationships recorded as current;
- final evidence from that runtime;
- task-specific hidden evidence and intermediate-state checks.

## Limits

Both arms use the same limits from `experiment/public/limits.json`:

- Codex execution timeout: 600 seconds.
- Maximum turns: 20.
- Maximum tool calls: 100.

Timeouts are failures within budget. Cost is not declared as a limit unless Codex reports usable cost telemetry.

Executor failures before meaningful task execution are classified as `invalid-censored`. Meaningful execution means the run recorded context events or invoked mobile build/install/launch activity before failing.

## Metrics

Primary metrics:

- independent task completion within 10 minutes;
- total wall-clock time to validation;
- Codex token usage when reported;
- environment-related failed attempts;
- stale or unverifiable source/artifact/runtime/evidence relationships.

Secondary metrics:

- turns and tool calls;
- agent-invoked builds, installs, launches, and observations;
- repeated environment discovery;
- raw-log volume exposed to Codex;
- evidence completeness;
- cost per successful task when reported.

The metric `provenSourceArtifactRuntimeEvidence` is true only when the ledger proves current source to artifact to installation to runtime to evidence relationships.

## Commands

Install pinned tools and run lightweight checks:

```bash
npm ci
python3 harness/doctor.py
python3 -m unittest discover -s tests
```

Create an experiment lock:

```bash
npm run lock
```

Run the one-attempt-per-arm pilot:

```bash
python3 harness/run_suite.py \
  --suite experiment/public/suites/pilot-eight-task-comparison.json \
  --execute-agent \
  --heartbeat-seconds 30
```

Run the post-pilot repeated state-intensive suite:

```bash
python3 harness/run_suite.py \
  --suite experiment/public/suites/repeat-state-intensive.json \
  --execute-agent \
  --heartbeat-seconds 30
```

Physical iPhone runs require:

```bash
export LOOPLAB_DEVICE_ID=<device-udid>
export LOOPLAB_DEVELOPMENT_TEAM=<team-id>
```

Evaluate or summarize preserved runs:

```bash
python3 harness/evaluate_run.py runs/<run-id>
python3 harness/metrics.py runs/<run-id>
python3 harness/report_baseline.py runs/suites/<suite-id>/suite-summary.json
```
