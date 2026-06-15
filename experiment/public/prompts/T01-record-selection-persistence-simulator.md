You are working on the LoopLab SwiftUI app in a fresh worktree.

Task: selecting a record should survive app process termination and relaunch on the simulator.

Requirements:
- A selected record must be restored after the app process is terminated and launched again.
- If the refreshed account data no longer contains the selected record, the app must safely clear that restored selection.
- Keep the native app buildable and make the behavior visible in the running app.
- Modify production app code; do not change validators, task metadata, or backend fixtures to satisfy the task.
- Preserve the final build, install, launch, and evidence paths under the shared run context directory.
