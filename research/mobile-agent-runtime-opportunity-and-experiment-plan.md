# Harness-Agnostic Mobile Development Runtime: Second-Opinion Report and Experiment Plan

Date: 2026-06-12

## Executive Conclusion

The suspected opportunity is real, but narrower than "agents need mobile control." The market already has several credible agent-facing mobile control layers:

- `agent-device` exposes mobile UI inspection, interaction, evidence, replay, logs, performance signals, physical-device support, and clean-state testing.
- XcodeBuildMCP covers a large part of iOS/macOS build, run, simulator, device, UI automation, logging, and debugging workflows for MCP-compatible agents.
- Mobile MCP, Maestro MCP, Appium, XCTest/XCUITest, ADB, Android Studio Agent Mode, Firebase Test Lab, BrowserStack, and AWS Device Farm all cover parts of build, automation, device access, or remote test execution.

The opportunity that remains is not another device driver, test runner, or MCP wrapper. It is a stateful coordination layer that maintains an authoritative relationship among:

- source revision and worktree
- build command, configuration, and artifact identity
- simulator/emulator/physical device identity and lease
- installed app binary and runtime process
- app data, permissions, OS/device state, and backend fixture state
- validation run, evidence bundle, logs, and final agent claim
- recovery actions and failure classification

That coordination is only partially addressed by current tools, usually inside one harness, one platform, one MCP server, or one test run. A harness-agnostic coordinator could add value if it behaves like a mobile environment control plane, not like a new automation framework.

## Research Basis

Primary and near-primary sources checked:

- OpenAI Codex manual and Codex iOS simulator use case: `https://developers.openai.com/codex/use-cases/ios-simulator-bug-debugging`
- `agent-device` README and docs: `https://github.com/callstack/agent-device`, `https://oss.callstack.com/agent-device/docs/introduction`, `https://oss.callstack.com/agent-device/docs/debugging-profiling`, `https://agent-device.dev/`
- XcodeBuildMCP site and repository: `https://www.xcodebuildmcp.com/`, `https://github.com/getsentry/XcodeBuildMCP`
- Mobile MCP repository: `https://github.com/mobile-next/mobile-mcp`
- Maestro MCP docs and site: `https://docs.maestro.dev/get-started/maestro-mcp`, `https://maestro.dev/`
- Appium docs: `https://appium.io/docs/en/latest/`
- Android Studio build/run and ADB docs: `https://developer.android.com/studio/run`, `https://developer.android.com/tools/adb`
- Apple XCTest/XCUIAutomation material: `https://developer.apple.com/videos/play/wwdc2025/344/`
- Detox device API: `https://wix.github.io/Detox/docs/19.x/api/device-object-api/`
- Cloud/device-farm docs: `https://firebase.google.com/docs/test-lab`, `https://docs.aws.amazon.com/devicefarm/latest/developerguide/welcome.html`, `https://www.browserstack.com/docs/app-automate/appium`

## What Existing Tools Already Cover

### Agent Harnesses

Codex already owns local work execution, worktrees, setup scripts, actions, MCP servers, hooks, skills/plugins, subagents, PR workflows, and terminal/tool execution. Its documented iOS simulator flow explicitly pairs Codex with XcodeBuildMCP so Codex can discover scheme/simulator, build, launch, inspect UI, tap/type/swipe, capture screenshots/logs, attach LLDB, patch, and re-run verification.

That substantially validates the premise that coding-agent harnesses should remain responsible for task reasoning and code editing. The candidate coordinator should not try to replace agent planning, repo inspection, patching, or PR workflows.

### Device-Control and Mobile Automation Layers

`agent-device` is already agent-native: it gives structured UI access, deterministic interactions, screenshots, recordings, logs, network traffic, traces, CPU/memory/perf snapshots, crash evidence, React Native component internals, physical-device support, and replayable flows. Its public positioning is explicitly "mobile app verification for AI agents."

XcodeBuildMCP is a strong iOS-specific counterexample to any claim that the ecosystem lacks build/run/debug controls for agents. It exposes project discovery, build/test/clean, simulator/device install and launch, UI automation, LLDB, logs, screenshots, video recording, and project-level defaults.

Mobile MCP and Maestro MCP show that MCP-compliant mobile automation is already active across Claude, Cursor, Codex, VS Code, Windsurf, and similar clients. Appium and Detox already provide app reset/install/launch semantics. ADB and Xcode/simctl already provide low-level device control.

### Cloud and Device-Farm Layers

BrowserStack, Firebase Test Lab, and AWS Device Farm cover remote real-device execution, logs, screenshots, videos, and scalable matrices. These are validation and infrastructure services, not inner-loop agent coordinators. They are relevant escalation targets for a coordinator, not substitutes for it.

## What Existing Tools Do Not Fully Cover

The gap is mostly a missing invariant ledger and policy engine.

### 1. Source-to-artifact-to-device consistency

Tools can build and install. They do not generally maintain a durable, queryable proof that:

- device D currently has artifact A installed
- artifact A was built from source revision R
- revision R included patch P from agent run N
- app process PID/session S corresponds to artifact A
- screenshots/logs E were captured after A was installed and after state reset profile Q was applied

This matters because mobile loops are vulnerable to stale binaries, incremental deploy edge cases, wrong simulator targets, reused devices, and screenshots from previous runs. Android Studio's own docs warn that incremental deployment can result in outdated code when app data is cleared between deployments unless package-manager install is forced.

### 2. Stateful environment lifecycle

Current tools provide primitives: boot, erase, install, launch, terminate, reset, clear logs, configure permissions, push notifications, set location, toggle settings. They do not usually decide, based on a persistent model, which reset or deploy level is required for this code change and validation intent.

The coordinator opportunity is in choosing among:

- hot reload / apply changes
- relaunch without reinstall
- install over existing app
- uninstall/reinstall
- simulator erase
- fresh simulator/emulator clone
- physical-device escalation

### 3. Multi-agent device leasing and isolation

Codex worktrees isolate source. ADB, simulators, Appium sessions, and agent-device sessions can target devices. The missing piece is a first-class lease binding between agent run, worktree, app id, build artifact, simulator/device, ports, backend fixtures, and evidence directory.

Without that, parallel agents can race on the same simulator, overwrite app state, attach to the wrong device, consume the wrong backend fixture, or validate each other's builds.

### 4. Backend and fixture coordination

Mobile app behavior often depends on auth state, push tokens, local storage, remote feature flags, seeded users, network mocks, and local backend processes. Device automation tools can interact with the app; they usually do not own the lifecycle of the backend fixture that makes the app state reproducible.

### 5. Failure classification and recovery policy

A coding agent can read logs and retry. Device tools can expose logs and restart services. The missing productized layer would classify failures as:

- build failure
- signing/provisioning failure
- stale artifact suspicion
- device boot failure
- app crash
- automation locator failure
- app state mismatch
- backend fixture failure
- network/tunnel failure
- permission/dialog blocker
- physical-device thermal/battery/connection issue

Then it can apply bounded recovery before handing control back to the agent.

### 6. Evidence normalization

Tools capture screenshots, logs, videos, traces, replay scripts, and reports, but evidence is not normally normalized into a portable run manifest tying each artifact to revision, build, environment state, action sequence, and final assertion. This is valuable for review, reproducibility, experiment measurement, and agent self-correction.

## Where I Disagree or Narrow the Suspected Gap

1. The opportunity is not broad "agentic mobile runtime." That phrasing overlaps too much with `agent-device`, XcodeBuildMCP, Mobile MCP, Maestro MCP, and Android Studio Agent Mode.

2. iOS simulator development is already much better covered than the initial premise implies. Codex plus XcodeBuildMCP plus an iOS debugger skill/plugin is already a credible closed loop for reproduce-debug-verify.

3. A candidate coordinator should probably not be a universal wrapper over Appium, XCTest, ADB, and `agent-device` on day one. It should expose a narrow contract and support pluggable executors. Otherwise it risks becoming a worse Appium/Maestro/agent-device.

4. The strongest wedge is reliability under repeated and concurrent agent runs, not single-agent demo capability. Single-agent demos already look good in existing tooling.

5. The most defensible product claim is "reduces stale environment and wasted iteration in native mobile agent loops," not "lets agents test mobile apps."

## Refined Candidate Definition

For experiment purposes, define the candidate system as:

Baseline stack plus a mobile environment coordinator that provides:

- Run manifest: source revision, worktree path, task id, build command, build output hash, artifact path/hash, target device, installed app id/version/build number, app process/session id, backend fixture id, validation steps, evidence paths.
- Lease manager: exclusive or shared leases for simulators/devices, app ids, ports, local backends, fixture users, and evidence directories.
- Deployment policy: decides hot reload/relaunch/reinstall/erase/fresh-device based on source changes, platform, app state requirement, previous run state, and stale-artifact risk.
- State profile: named app/device/backend restoration policies, such as `warm_logged_in`, `fresh_install`, `permission_matrix`, `offline`, `push_ready`, or `seeded_cart`.
- Health monitor: checks simulator/device readiness, adb server, boot state, app liveness, log stream availability, backend availability, and physical-device constraints.
- Recovery policy: bounded automatic repair for known environment failures, with clear escalation when recovery would contaminate the experiment.
- Evidence normalizer: stores screenshots, logs, videos, traces, UI snapshots, replay scripts, build logs, failure classifications, and final assertions in a standard evidence bundle.
- Adapter layer: calls existing tools such as `agent-device`, XcodeBuildMCP, ADB, xcodebuild/simctl, Gradle, Appium, Maestro, and cloud device farms rather than replacing them.

This is enough to test the hypothesis without prematurely designing the production architecture.

## Experiment Goal

Answer:

Does adding a mobile environment coordinator improve agentic coding tool performance on closed-loop native mobile development tasks?

The experiment should distinguish three effects:

- Faster observation: less time between code edit and trustworthy app observation.
- Better reliability: fewer environment-induced failures, stale artifacts, and invalid validations.
- Better outcomes: higher task completion rate or same completion rate with lower cost/latency.

## Experimental Systems

### Baseline

Codex plus the best current ancillary tooling:

- Codex as the coding agent and task harness.
- Native build tools: Xcode/xcodebuild/simctl for iOS; Gradle/Android Studio command-line/ADB for Android.
- `agent-device` for UI snapshots, interactions, evidence, logs, performance data, replay, and physical-device operation where applicable.
- XcodeBuildMCP for iOS build/run/debug/simulator automation if available and relevant.
- Maestro MCP or Maestro CLI for deterministic mobile flows where a task benefits from a scripted validation.
- Appium only where the test fixture already uses Appium or where Appium provides a stronger existing baseline.
- Repository-local scripts, AGENTS.md instructions, Codex local environment setup, and hooks that a competent team would reasonably provide.

This must be a strong baseline. Do not compare the coordinator against a deliberately under-tooled agent.

### Candidate

Same stack plus the coordinator behavior listed above. The candidate can use the same underlying tools. It wins only if coordination improves measured performance beyond what those tools already provide.

## Task Corpus

Use 40-80 tasks across at least two app codebases:

- One native iOS app in Swift/SwiftUI/UIKit.
- One native Android app in Kotlin/Jetpack Compose/View system.
- Optional third React Native app only if cross-platform mobile is strategically important.

Each task should have:

- initial repo revision
- task prompt
- hidden expected behavior
- deterministic or semi-deterministic validation flow
- required state profile
- seeded backend or mock fixture, if applicable
- maximum wall-clock budget
- success rubric
- known failure oracle independent from the agent's own claim

Task categories:

- UI bug requiring reproduce-fix-verify
- feature addition with visible UI change
- navigation/state persistence bug
- permission/onboarding flow bug
- backend/fixture-dependent behavior
- push/deep-link behavior
- flaky or slow runtime issue
- crash/hang with logs
- styling/layout regression
- physical-device-only or simulator-to-device escalation task

Include both easy and hard tasks. At least 25-35% should require nontrivial state restoration or backend/device coordination; otherwise the coordinator is not being tested.

## Experimental Design

Use a paired crossover design.

For each task, run both systems from the same initial repo revision and environment snapshot. Randomize order:

- Half the tasks: baseline first, candidate second.
- Half the tasks: candidate first, baseline second.

Use fresh worktrees, fresh evidence directories, and fresh coordinator/baseline logs for each run. Reset devices according to the task's declared initial state. For any physical-device runs, rotate devices and randomize assignment to reduce device-specific bias.

Run at least 3 independent attempts per system/task if budget allows. If cost is constrained, run 1 attempt across a larger task corpus first, then rerun the most discriminating 20-30 tasks with 3 attempts.

Keep constant:

- model and reasoning settings
- Codex version/surface
- repository instructions
- maximum wall-clock time
- maximum token budget
- starting branch/revision
- device OS versions where feasible
- backend fixture version
- validation oracle

Vary only the availability of the coordinator.

## Primary Metrics

### Feature completion rate

Definition: percentage of runs that pass the independent validation oracle and code review sanity check within budget.

Use as the primary outcome metric. The coordinator only matters if it preserves or improves final success.

### Edit-to-observation latency

Definition: time from the final file edit before a validation attempt to the first trustworthy app observation tied to the new artifact.

Trustworthy means the evidence manifest proves the observation came from the artifact built from the post-edit source revision.

Report median, p75, and p95.

### Environment failure rate

Definition: failures caused by environment/tooling rather than incorrect product code. Examples: wrong device, stale binary, app not installed, build artifact mismatch, adb/simctl unavailable, backend fixture missing, permission state wrong, log stream missing.

Report per run and per validation attempt.

### Stale or incorrect artifact usage

Definition: any validation attempt where the installed/running app cannot be proven to match the intended source revision/artifact, or is later proven mismatched.

This is a primary metric because it directly targets the suspected gap.

## Secondary Metrics

- Token usage: total input/output tokens per completed task and per failed task.
- Wasted agent iterations: iterations spent diagnosing/fixing an environment issue as if it were an app-code issue.
- Unnecessary rebuilds/reinstalls: deploy operations that did not change the observable artifact or were stronger than required by policy.
- Automatic recovery rate: percentage of environment failures recovered without user intervention and without contaminating state.
- State-restoration reliability: percentage of validations that start from the declared app/device/backend state.
- Concurrent-agent reliability: completion rate and environment failure rate under N parallel tasks.
- Physical-device strain: battery delta, thermal state if available, charge cycles avoided, install count, screen-on time, CPU/memory/perf samples.
- Evidence quality: percentage of final answers with complete manifest, screenshots/logs/replay where required, and reproducible validation steps.
- Cost-to-success: tokens plus wall-clock plus device minutes per successful task.

## Instrumentation Requirements

Both baseline and candidate need comparable telemetry. Add passive logging around:

- every build command, start/end time, exit code, artifact path/hash
- every install/reinstall/uninstall/relaunch
- device id, OS version, boot state, battery/thermal if physical
- app id, version/build number, process id/session id where available
- source revision before build and before validation
- backend fixture id and reset/seed events
- all screenshots/log/video/trace paths
- all agent validation claims
- all recovery actions and their trigger classification
- token usage and tool-call counts

The baseline may not have a coordinator manifest, but the experiment harness must still log enough externally to measure it fairly. Otherwise the candidate wins by being easier to observe rather than by improving actual performance.

## Failure Taxonomy

Use mutually exclusive top-level labels:

- `agent_code_error`: agent changed code incorrectly.
- `agent_validation_error`: agent failed to verify or misread evidence.
- `build_error`: compile/package/signing failure.
- `stale_artifact`: running app did not match intended source/artifact.
- `device_unavailable`: simulator/emulator/physical device not ready, disconnected, hung, or wrong target.
- `app_runtime_error`: crash/hang/ANR caused by app behavior after correct artifact deployment.
- `automation_error`: UI locator/action failure not caused by intended app behavior.
- `state_error`: app permissions/data/backend fixture/deep link/push state not as required.
- `backend_error`: local/remote backend unavailable or incorrectly seeded.
- `infrastructure_error`: host resource, network, disk, toolchain, or CI failure.
- `unknown`: insufficient evidence.

Require two reviewers or a reviewer plus deterministic rule for ambiguous failures.

## Concurrent-Agent Subexperiment

Run 2, 4, and 8 concurrent tasks across separate worktrees.

Measure:

- wrong-device or wrong-artifact incidents
- port/backend fixture collisions
- simulator/emulator boot conflicts
- physical-device contention
- evidence directory collisions
- completion rate degradation from single-agent mode
- mean queue time for device leases

This is likely where the coordinator's effect is strongest.

## Physical Device Subexperiment

Use only a subset of tasks that plausibly need physical hardware:

- camera, biometrics, push notifications, Bluetooth/NFC if relevant, performance/thermal, real network behavior, OEM-specific Android behavior.

Measure:

- device minutes
- install/reinstall count
- battery delta
- thermal state changes if available
- screen-on time
- recovery from disconnect/lock/sleep
- success uplift from simulator-to-physical escalation

Do not let this dominate the main experiment unless physical-device reliability is the primary product thesis.

## Statistical Analysis

Pre-register:

- primary outcome: feature completion rate
- primary process metrics: edit-to-observation latency, stale artifact rate, environment failure rate
- secondary metrics listed above

For paired binary outcomes, use McNemar's test or a mixed-effects logistic model with task and app as random effects. For latency/token metrics, use paired nonparametric tests and report effect sizes with confidence intervals. For repeated attempts, use hierarchical models or summarize per task/system first to avoid pseudo-replication.

Recommended minimum:

- Pilot: 10 tasks x 2 systems x 1 attempt, used only to debug harness and metric definitions.
- Main: 40 tasks x 2 systems x 3 attempts = 240 runs.
- Concurrency: 12 selected tasks x 2 systems x 3 concurrency levels.

Success threshold should require both:

- statistically credible improvement in at least one primary process metric directly tied to coordination
- no regression in feature completion rate

A strong win would be:

- at least 30% reduction in stale/incorrect artifact incidents
- at least 20% reduction in environment failures
- at least 15% reduction in edit-to-observation p75 latency
- neutral or improved completion rate
- neutral or reduced token usage per successful task

## Guardrails Against Biased Results

- Use a strong baseline with XcodeBuildMCP/agent-device/Maestro where appropriate.
- Do not let the candidate use a better validation oracle than baseline.
- Do not count coordinator-generated manifests as success evidence unless they tie to externally captured artifacts.
- Keep prompts equivalent. The baseline prompt may include best-practice instructions that mirror what a skilled mobile developer would tell Codex.
- Randomize run order.
- Freeze app repos and task prompts before main runs.
- Separate pilot tuning from final measurement.
- Blind human review of final patches where possible.
- Preserve all logs and evidence for audit.

## Decision Rules

Proceed to coordinator architecture only if the experiment would be able to detect the suspected effect. Before implementation, confirm:

- The baseline has recurring measurable failures in stale artifacts, state restoration, environment recovery, or concurrency.
- These failures are not solvable by a simpler Codex skill, AGENTS.md instruction, hook, or per-platform MCP configuration.
- The candidate's responsibilities are mostly coordination and evidence, not duplicated device automation.

Stop or narrow the product thesis if pilot data shows:

- baseline environment failures are rare
- most task failures are pure code-reasoning failures
- XcodeBuildMCP/agent-device already eliminate stale-artifact and state issues with simple instructions
- coordinator overhead increases latency more than it reduces retries

## Bottom Line

The validated gap is a mobile environment coordination and evidence-control plane for agentic development. It should be harness-agnostic and executor-pluggable. Its value should be tested primarily on stale artifact prevention, state restoration, recovery, and concurrent-agent reliability, not on whether an agent can tap through an app.
