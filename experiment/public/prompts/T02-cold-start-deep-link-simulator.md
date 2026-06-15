You are working on the LoopLab SwiftUI app in a fresh worktree.

Task: record deep links should navigate correctly when the app is launched from a terminated state on the simulator.

Requirements:
- Preserve existing warm-link behavior when the app is already running.
- A cold-start record link must open the matching record detail after launch completes.
- Unknown records must be handled safely without leaving the app in a misleading detail state.
- Modify production app code; do not change validators, task metadata, or backend fixtures to satisfy the task.
- Preserve the final build, install, launch, deep-link, and evidence paths under the shared run context directory.
