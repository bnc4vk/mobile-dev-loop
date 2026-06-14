# Candidate Coordinator

This directory is candidate-only. Baseline executor worktrees remove `candidate/` before task execution so baseline runs cannot inspect or use coordinator code.

Candidate executor worktrees expose `candidate/bin` on `PATH`, so agents can call the coordinator as `mobile-loop`.

Primary executor-facing commands:

- `mobile-loop status`
- `mobile-loop preflight --task <task-id>`
- `mobile-loop validate --task <task-id>`

`mobile-loop validate` uses only public task metadata and primitive local tools. It builds the app, starts a deterministic clean mock backend, installs/launches the app on the requested simulator or iPhone target, captures `agent-device` evidence, writes `runs/mobile-loop-*/mobile-loop-result.json`, and returns non-zero when public evidence checks fail. Terminal output is compact by default; pass `--verbose` to print the full command ledger. Hidden validators and private fault profiles are not exposed to the executor.

The first coordinator surface is intentionally narrow:

- normalize run identity across source, artifact, installed runtime, device, backend fixture, and evidence;
- classify current runtime health from existing telemetry and metrics;
- recommend the next transition among `reuse-observation`, `relaunch`, `reinstall`, `rebuild`, and `reset`;
- recover a broken `agent-device` runner lease by clearing the run-local lease and retrying evidence capture;
- recover a failed install caused by a corrupt run-local build artifact by rebuilding from the same source revision and retrying install/launch;
- recover a killed app runtime by relaunching and retrying evidence capture once;
- restore a run-local backend from an injected stale fixture or HTTP failure to the task's expected fixture state;
- emit a machine-readable coordinator manifest for later candidate integration.

Current active behavior is limited to the observation transition, backend restoration, broken-runner recovery, failed-install recovery, and runtime relaunch recovery. Candidate runs ask the coordinator whether to `reuse-observation` or `relaunch` before `agent-device` evidence capture. If a controlled backend fault starts a stale fixture or HTTP failure, the coordinator records a fixture restoration transition and the harness restarts the run-local backend with the expected task fixture. If a controlled broken-runner fault produces untrusted evidence, the coordinator removes the run-local runner lease, records the recovery in its manifest, and the harness retries evidence capture once. If a controlled failed-install fault corrupts the app bundle, the coordinator records a rebuild transition and the harness clears run-local DerivedData, rebuilds from the same worktree, and retries install/launch once. If a controlled runtime fault kills the app after automation opens it, the coordinator records a relaunch transition and the harness retries evidence capture once. On physical iPhone runs, `relaunch` is satisfied by the harness' preceding `devicectl launch --terminate-existing` step and the `agent-device open` call attaches without its own `--relaunch` flag. The coordinator does not yet choose fresh-device reset actions.
