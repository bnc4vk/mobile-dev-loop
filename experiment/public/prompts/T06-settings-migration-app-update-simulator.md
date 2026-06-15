You are working on the LoopLab SwiftUI app in a fresh worktree.

Task: a user preference stored by an older app version should survive installing the updated app over it on the simulator.

Requirements:
- Implement an idempotent migration for the renamed persisted setting.
- Installing the updated app over the older app must preserve the existing preference.
- Uninstalling and reinstalling the app must not be used as the solution.
- Modify production app code; do not change validators, task metadata, or backend fixtures to satisfy the task.
- Preserve the old-version setup, update install, final launch, and evidence paths under the shared run context directory.
