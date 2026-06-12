# Mobile Environment Coordinator: Phase 1 Experiment Plan

Date: 2026-06-12

## 1. Hypothesis

Adding a harness-agnostic mobile environment coordinator to a strong iOS development stack driven by an agentic coding tool will produce visibly better closed-loop mobile development performance when physical iPhone execution, signing/install reliability, app/device state restoration, and simulator-to-device escalation are part of the loop.

Phase 1 is a low-density screening experiment. It should answer whether the coordinator creates obvious value on source-to-artifact-to-installed-app identity, reliable physical-device execution, state restoration, bounded recovery from injected failures, and edit-to-trustworthy-observation latency. If the candidate does not show clear improvement on these dimensions, the product thesis should be narrowed or stopped.

Scope:

- One native SwiftUI app.
- 8-10 tasks.
- At least two runs per task per group where practical.
- Approximately 40-50% of tasks require or materially benefit from a physical iPhone.
- Physical-device tasks focus on environment coordination, not unusually difficult AVFoundation implementation.
- Same task corpus for both groups.
- Success judged by independent validation, not by the agent's final claim alone.
- Bounded stopping rules based on turns, tool calls, cost, and process timeout.

## 2. Experiment Groups

| Baseline | Candidate |
| --- | --- |
| **Agentic coding tool + current best iOS mobile tooling**<br><br>- Agentic coding tool owns reasoning, editing, shell, Git, worktree, and final answer.<br>- Xcode/xcodebuild/simctl handle native build, signing, install, launch, simulator, and physical-device operations.<br>- `agent-device` handles semantic UI inspection, interaction, logs, screenshots, profiling, replay, and physical-device interaction where applicable.<br>- XcodeBuildMCP is available for iOS build/run/debug/simulator workflows where compatible with the selected agentic coding tool.<br>- Repository scripts, tool-specific project instructions, local environment setup, hooks, and existing validation scripts are allowed.<br>- Baseline telemetry is passive: it observes outcomes but does not restore state, classify failures, or guide recovery.<br>- No persistent external coordinator tracks artifact/device/app/backend/evidence invariants. | **Baseline + mobile environment coordinator**<br><br>- Same agentic coding tool, model, prompts, repo, devices, and tools as baseline.<br>- Coordinator maintains run manifest tying source revision, build artifact, signing/install event, installed app, device lease, app state, backend fixture, validation action, and evidence.<br>- Coordinator chooses reload/relaunch/reinstall/rebuild/fresh-device-reset/escalation policy from source changes and declared state needs.<br>- Coordinator owns simulator, physical-device, app, permission, account, backend-fixture, automation-session, and evidence leases for the run.<br>- Coordinator performs bounded health checks and automatic recovery for known environment failures.<br>- Coordinator normalizes screenshots, logs, traces, replay, failure classification, and final validation evidence. |

## 3. Enumerated Task List

Use one native SwiftUI app. Each task starts from a fixed repo revision and has a hidden expected behavior plus an independent validation oracle. Faults are injected by the experiment harness, not by changing the agent prompt.

1. Clean simulator control: fix a simple SwiftUI list rendering bug, then validate on simulator with no injected fault. Tests coordinator overhead, edit-to-trustworthy-observation latency, and unnecessary rebuild/reinstall behavior.
2. Clean physical-iPhone control: fix a simple device-visible settings label, then validate on a physical iPhone with no injected fault. Tests coordinator overhead, signing/install/launch reliability, and unnecessary physical-device usage.
3. Stale installed build: fix a visible copy/state bug while the target simulator starts with an older installed build. Tests source revision -> build artifact -> installed app identity and stale-artifact detection.
4. Incorrect permission state: fix camera-permission recovery copy and CTA behavior while the physical iPhone starts with the wrong camera permission state. Tests app/permission state restoration without requiring complex camera implementation.
5. Stale backend fixture: fix empty-state rendering for a seeded account while the backend fixture initially points at stale account data. Tests account and backend-fixture restoration.
6. Broken automation runner: fix a navigation bug while the first automation session is deliberately broken or unavailable. Tests automation-session health checks and bounded recovery.
7. Failed install: fix a small detail-screen behavior while the first physical-iPhone install attempt is deliberately failed. Tests signing, installation, launch, and recovery reliability.
8. Locked or disconnected iPhone: fix a hardware-visible camera preview label/orientation issue while the physical iPhone starts locked or disconnected. Tests device lease health, unlock/reconnect handling, and physical-device observation.
9. Simulator-to-physical escalation: fix a QR/deep-link capture flow that can be partly validated on simulator but requires real camera input for final validation. Tests correct simulator-to-device escalation and avoids hard AVFoundation changes.
10. Runtime failure and reset policy: fix login/logout state persistence while the app process is deliberately killed during one validation attempt and the declared initial state requires a clean app install plus fresh account fixture. Tests relaunch versus reinstall versus rebuild versus fresh-device reset choice.

## 4. Constants

1. Same agentic coding tool and product surface for a given experiment run.
2. Same model and reasoning settings.
3. Same task prompt for both groups.
4. Same initial branch/revision per task.
5. Same native SwiftUI app codebase and dependency lockfiles.
6. Same Xcode version, iOS SDK, simulator runtime, and physical-device OS version where feasible.
7. Same physical-device pool for hardware tasks, with assignment recorded.
8. Same `agent-device`, XcodeBuildMCP, xcodebuild, and simctl versions.
9. Same validation oracle and human review rubric.
10. Same backend fixture version and seed data.
11. Same controlled fault injection for both groups: stale installed build, incorrect permission state, broken automation runner, disconnected or locked device, stale fixture, failed install, and clean runs.
12. Same evidence requirements.
13. Same number of runs: target at least two baseline runs and two candidate runs per task where practical.
14. Fresh top-level agent thread and fresh worktree for every task/group/run.
15. Same hardware assignment policy across groups, with device id and OS version recorded.
16. Subagents may be used only if equally available to both groups.
17. Bounded stopping rules are identical across groups: maximum turns, maximum tool calls, maximum cost, and maximum process timeout.
18. Record elapsed time even when a run hits a stopping rule.

## 5. Primary and Secondary Metrics

### Primary Metrics

1. Trustworthy artifact-validation rate: percentage of validations where the observed app is proven to match the intended source revision, build artifact, signing/install event, and target device.
2. State-restoration success: percentage of validations starting from the declared app, permission, account, backend-fixture, simulator, and physical-device state.
3. Automatic environment-recovery success: percentage of injected environment faults recovered without user intervention and without contaminating validation state.
4. Wasted agent iterations caused by infrastructure: turns or tool-call clusters spent diagnosing environment faults as product-code issues.
5. Edit-to-trustworthy-observation latency: time from final relevant edit before validation to first trustworthy observation tied to the new artifact and intended device state.
6. Unnecessary builds, reinstalls, and resets: avoidable build/install/reset operations relative to the declared policy and actual source/app state.
7. Successful simulator-to-device escalation: percentage of tasks requiring real iPhone validation where the run escalates at the right time and preserves artifact/state continuity.
8. Final task completion: whether the final patch passes the independent oracle and review sanity check.

### Secondary Metrics

1. Token usage per task.
2. Total turns and tool calls per task.
3. Process timeout, cost-limit, or tool-call-limit hits.
4. Signing, install, launch, and automation-session failure counts.
5. Recovery action count by type: relaunch, reinstall, rebuild, simulator reset, fresh-device reset, backend fixture restore, physical-device reconnect/unlock.
6. Evidence completeness: build log, artifact identity, signing/install record, device identity, app state, screenshots/logs/replay, and final validation record.
7. Physical-device strain for hardware tasks: install count, device minutes, screen-on time, battery delta, and thermal state if available.

## 6. Guardrails Against Biased Results

1. Use a strong baseline with the selected agentic coding tool, `agent-device`, XcodeBuildMCP, native Xcode tooling, repo scripts, and reasonable project instructions.
2. Do not give the candidate a better validation oracle, better task prompt, or better model settings.
3. Run both groups from the same starting revision and fixture state for each task.
4. Preserve the original combined report for context and do not tune task design after seeing final outcomes.
5. Use fresh top-level agent threads and fresh worktrees for every task/group/run.
6. Keep baseline telemetry passive: it may observe outcomes, but it must not restore state, classify failures, or guide recovery.
7. Record enough baseline telemetry externally to measure artifact identity, device identity, app state, and evidence quality fairly.
8. Do not count coordinator-generated manifests as truth unless they tie to externally captured artifacts.
9. Randomize whether baseline or candidate runs first for each task when practical.
10. Keep hardware assignment identical or counterbalanced across groups.
11. Include clean simulator and clean physical-device runs so coordinator overhead is measurable.
12. Use physical hardware for the 40-50% of tasks that require or materially benefit from it; otherwise prefer the same simulator runtime for both groups.
13. Blind final patch review where feasible.
14. Preserve all logs, screenshots, replays, build artifacts, run manifests, telemetry, and fault-injection records for audit.
