You are working on the LoopLab SwiftUI app in a fresh worktree.

Task: malformed account data from the backend should be recoverable on the simulator.

Requirements:
- Malformed account data must not crash the app or leave unsafe stale state.
- Show a recoverable error state that makes the failure visible.
- After the backend returns valid data, retry should load and display the valid account.
- Modify production app code; do not change validators, task metadata, or backend fixtures to satisfy the task.
- Preserve the final build, install, launch, malformed-data evidence, retry evidence, and valid-data evidence paths under the shared run context directory.
