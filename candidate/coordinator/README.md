# Candidate Coordinator

This directory is candidate-only. Baseline executor worktrees remove `candidate/` before task execution so baseline runs cannot inspect or use coordinator code.

The first coordinator surface is intentionally passive:

- normalize run identity across source, artifact, installed runtime, device, backend fixture, and evidence;
- classify current runtime health from existing telemetry and metrics;
- recommend the next transition among `reuse-observation`, `relaunch`, `reinstall`, `rebuild`, and `reset`;
- emit a machine-readable coordinator manifest for later candidate integration.

It does not yet recover state, mutate devices, or enable candidate experiment runs.
