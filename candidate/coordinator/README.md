# Candidate Coordinator

This directory is candidate-only. Baseline executor worktrees remove `candidate/` before task execution so baseline runs cannot inspect or use coordinator code.

The first coordinator surface is intentionally narrow:

- normalize run identity across source, artifact, installed runtime, device, backend fixture, and evidence;
- classify current runtime health from existing telemetry and metrics;
- recommend the next transition among `reuse-observation`, `relaunch`, `reinstall`, `rebuild`, and `reset`;
- recover a broken `agent-device` runner lease by clearing the run-local lease and retrying evidence capture;
- emit a machine-readable coordinator manifest for later candidate integration.

Current active behavior is limited to the observation transition and broken-runner recovery. Candidate runs ask the coordinator whether to `reuse-observation` or `relaunch` before `agent-device` evidence capture. If a controlled broken-runner fault produces untrusted evidence, the coordinator removes the run-local runner lease, records the recovery in its manifest, and the harness retries evidence capture once. On physical iPhone runs, `relaunch` is satisfied by the harness' preceding `devicectl launch --terminate-existing` step and the `agent-device open` call attaches without its own `--relaunch` flag. The coordinator does not yet choose rebuild, reinstall, reset, or fixture restoration actions.
