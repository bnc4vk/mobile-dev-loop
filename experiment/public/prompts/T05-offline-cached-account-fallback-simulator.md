You are working on the LoopLab SwiftUI app in a fresh worktree.

Task: after a successful account load, relaunching while the backend is unavailable should show useful cached data on the simulator.

Requirements:
- Persist the last valid account response.
- When live data cannot be loaded, show the cached account and clearly indicate that it is cached or offline.
- When live data becomes available again, replace cached data with live data.
- Modify production app code; do not change validators, task metadata, or backend fixtures to satisfy the task.
- Preserve the final build, install, launch, offline transition, live-recovery transition, and evidence paths under the shared run context directory.
