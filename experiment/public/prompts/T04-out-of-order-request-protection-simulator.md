You are working on the LoopLab SwiftUI app in a fresh worktree.

Task: overlapping account reloads must not allow an older response to overwrite newer data on the simulator.

Requirements:
- When multiple reloads overlap, the newest requested result must win.
- The behavior must hold under deterministic timing permutations.
- Keep user-visible loading and error states coherent while requests overlap.
- Modify production app code; do not change validators, task metadata, or backend fixtures to satisfy the task.
- Preserve the final build, install, launch, request-timing evidence, and UI evidence paths under the shared run context directory.
