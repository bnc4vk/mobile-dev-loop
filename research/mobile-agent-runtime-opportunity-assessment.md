# Harness-Agnostic Mobile Runtime: Opportunity Assessment

Date: 2026-06-12

## Executive Conclusion

The suspected opportunity is real, but narrower than "agents need mobile control." Existing tools already provide credible agent-facing mobile execution and observation:

- `agent-device` exposes mobile UI inspection, interaction, evidence, replay, logs, performance signals, physical-device support, and clean-state testing.
- XcodeBuildMCP covers much of the iOS/macOS build, run, simulator, device, UI automation, logging, and debugging loop for MCP-compatible agents.
- Mobile MCP, Maestro MCP, Appium, XCTest/XCUITest, ADB, Android Studio Agent Mode, Firebase Test Lab, BrowserStack, and AWS Device Farm all cover parts of build, automation, device access, or remote test execution.

The remaining opportunity is not another device driver, test runner, or MCP wrapper. It is a stateful coordination layer that maintains an authoritative relationship among:

- source revision and worktree
- build command, configuration, and artifact identity
- simulator/emulator/physical-device identity and lease
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

That validates the premise that coding-agent harnesses should remain responsible for task reasoning and code editing. The candidate coordinator should not try to replace agent planning, repo inspection, patching, or PR workflows.

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

This matters because mobile loops are vulnerable to stale binaries, incremental deploy edge cases, wrong simulator targets, reused devices, and screenshots from previous runs.

### 2. Stateful environment lifecycle

Current tools provide primitives: boot, erase, install, launch, terminate, reset, clear logs, configure permissions, push notifications, set location, toggle settings. They do not usually decide, based on a persistent model, which reset or deploy level is required for a particular code change and validation intent.

The coordinator opportunity is in choosing among:

- hot reload / apply changes
- relaunch without reinstall
- install over existing app
- uninstall/reinstall
- simulator erase
- fresh simulator/emulator clone
- physical-device escalation

### 3. Multi-agent device leasing and isolation

Codex worktrees isolate source. ADB, simulators, Appium sessions, and `agent-device` sessions can target devices. The missing piece is a first-class lease binding between agent run, worktree, app id, build artifact, simulator/device, ports, backend fixtures, and evidence directory.

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

## Where The Gap Should Be Narrowed

1. The opportunity is not broad "agentic mobile runtime." That phrasing overlaps too much with `agent-device`, XcodeBuildMCP, Mobile MCP, Maestro MCP, and Android Studio Agent Mode.

2. iOS simulator development is already much better covered than the initial premise implies. Codex plus XcodeBuildMCP plus an iOS debugger skill/plugin is already a credible closed loop for reproduce-debug-verify.

3. A candidate coordinator should not start as a universal wrapper over Appium, XCTest, ADB, and `agent-device`. It should expose a narrow contract and support pluggable executors. Otherwise it risks becoming a worse Appium/Maestro/agent-device.

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

## Bottom Line

The validated gap is a mobile environment coordination and evidence-control plane for agentic development. It should be harness-agnostic and executor-pluggable. Its value should be tested primarily on stale artifact prevention, state restoration, recovery, and concurrent-agent reliability, not on whether an agent can tap through an app.
