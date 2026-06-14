# Construction Plan

Date: 2026-06-12

## Repository Structure

- `apps/LoopLab/`: one purpose-designed native SwiftUI app for all Phase 1 tasks.
- `backend/`: deterministic local mock backend with named fixtures and injectable failures.
- `experiment/public/`: task prompts, public task metadata, fixed limits, and tool version locks available to executors.
- `experiment/private/`: hidden validators, expected patch references, and fault-injection controls. These must be excluded from executor worktrees during real runs.
- `candidate/`: candidate-only coordinator code. Baseline executor worktrees remove this directory before task execution.
- `harness/`: reusable run harness, passive telemetry, artifact collection, and run-state isolation.
- `runs/`: generated run artifacts, logs, manifests, screenshots, and telemetry. Ignored by Git.
- `docs/`: research, design notes, and locked experiment process.

## Phased Implementation Sequence

1. Foundation: create the SwiftUI app, mock backend, task metadata, passive telemetry schema, and harness entrypoint.
2. Manual validation: confirm one clean simulator task and one clean physical-iPhone task reproduce the intended initial fault and pass the independent oracle after the expected patch.
3. Baseline environment: make baseline runs reliable with passive telemetry only; do not add coordinator recovery or classification.
4. Fault injection: add controlled stale build, permission, automation runner, locked/disconnected device, stale fixture, failed install, and runtime kill faults.
5. Full baseline lock: freeze app, tasks, prompts, faults, limits, validators, tool versions, signing assets, hardware, and cache policy.
6. Candidate coordinator: implement the minimal coordinator only after baseline execution works end to end.
7. Experiment execution: randomize baseline/candidate ordering, preserve all runs, and evaluate with independent validators.

## Thread Roles

- Builder thread: owns app, backend, harness, and coordinator implementation.
- Executor thread: runs baseline or candidate condition from public prompts only.
- Evaluator thread: runs hidden validators, reviews evidence, classifies outcomes, and preserves artifacts.

## Cache Policy

Phase 1 should use equivalent cold starts unless pilot runs show setup overhead dominates the signal. Cold start means fresh worktree, isolated Derived Data, fresh backend process/port, fresh `agent-device` state, fresh simulator/device lease, and no reused app install unless the task explicitly injects a stale installed build.

If prewarmed caches are used later, both groups must receive the same prewarming: dependency cache, Xcode module cache, simulator boot state, and hardware readiness.

## First End-to-End Slice

The first runnable slice should support:

1. One clean simulator task:
   - build app from fresh worktree
   - start mock backend with a named fixture
   - boot/select simulator
   - install and launch app
   - collect passive telemetry and artifacts

2. One clean physical-iPhone task:
   - build app for device with configured signing
   - install and launch on an explicitly selected iPhone
   - collect signing/install/launch telemetry and artifacts

Physical-device execution requires local signing configuration and a trusted attached device. The harness should fail clearly when those are not configured.

## Shared Tooling Setup

Shared executor tooling is repo-local and pinned through `package-lock.json`:

- `agent-device@0.17.3`
- `xcodebuildmcp@2.6.2`

Run:

```bash
npm ci
python3 harness/doctor.py
```

For deeper XcodeBuildMCP diagnostics:

```bash
python3 harness/doctor.py --deep
```

The repo pins a local `node@24.14.0` dev dependency so npm scripts and project MCP tooling do not depend on a global Node version.

Project-scoped Codex MCP configuration lives in `.codex/config.toml` and starts XcodeBuildMCP through the local npm package and local pinned Node runtime. The run harness links each fresh executor worktree to the root immutable `node_modules` so the executor sees the same pinned tools without installing mutable dependencies inside each run.

## Experiment Locking

Before any real baseline/candidate comparison run, generate a lock manifest:

```bash
npm run lock
```

The lock hashes the SwiftUI app, backend, harness, public task metadata/prompts/suites, private faults/validators, package lock, and tool-version metadata into `runs/locks/experiment-lock.json`. Use `--include-devices` when freezing a hardware-specific execution window. The lock is an experiment artifact, not executor input.
