You are working on the LoopLab SwiftUI app in a fresh worktree.

Task: camera permission changes made in iOS Settings while the physical iPhone app is backgrounded should be reflected after returning to the app.

Requirements:
- Refresh the displayed camera permission state on the correct lifecycle transition.
- Do not automatically prompt for camera permission as part of the refresh.
- Existing manual permission request behavior should continue to work.
- Modify production app code; do not change validators, task metadata, or backend fixtures to satisfy the task.
- Preserve the final build, install, launch, Settings transition, and evidence paths under the shared run context directory.
