# Local Configuration

The harness reads optional local defaults from:

```bash
experiment/local.env
```

This file is intentionally ignored by Git because it may contain machine-specific
device identifiers and Apple signing team IDs. It is loaded only when the
corresponding environment variable is not already set.

For this workspace, the file should contain:

```bash
LOOPLAB_DEVICE_ID=00008140-001265180AC2801C
LOOPLAB_DEVELOPMENT_TEAM=TDSBZM3Z79
```

Explicit shell exports or harness flags still take precedence:

```bash
python3 harness/run_suite.py \
  --suite experiment/public/suites/pilot-eight-task-comparison.json \
  --allow-candidate \
  --execute-agent \
  --device-id "$LOOPLAB_DEVICE_ID" \
  --development-team "$LOOPLAB_DEVELOPMENT_TEAM"
```

Check whether the values are discoverable:

```bash
python3 harness/doctor.py --json
```
