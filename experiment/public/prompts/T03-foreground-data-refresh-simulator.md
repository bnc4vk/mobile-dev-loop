You are working on the LoopLab SwiftUI app in a fresh worktree.

Task: account data should refresh when the simulator app returns to the foreground after the backing data has changed.

Requirements:
- Returning from background should refresh visible account data.
- The refresh must avoid uncontrolled duplicate requests during normal foreground transitions.
- Existing manual reload behavior should continue to work.
- Modify production app code; do not change validators, task metadata, or backend fixtures to satisfy the task.
- Preserve the final build, install, launch, backend transition, and evidence paths under the shared run context directory.
