# mobile-dev Candidate Layer

`mobile-dev` is the candidate-only treatment. Baseline executor worktrees remove `candidate/`, so baseline runs cannot inspect or use this code.

Executor-facing commands:

- `mobile-dev record <operation> ...`
- `mobile-dev run --operation <name> --provider <tool> -- <single provider command ...>`
- `mobile-dev status`
- `mobile-dev history`

The layer only normalizes one recorded or wrapped provider result at a time, preserves raw output under `LOOPLAB_RUN_CONTEXT_DIR/raw-output/`, appends to `ledger.jsonl`, and materializes `state.json`.

It does not build workflows, validate tasks, choose recovery actions, restart services, repair artifacts, clear runner leases, or know task-specific oracle details.
