# Validator Contract

Validators must be deterministic and independent from agent self-reported success.

Each validator receives:

- run manifest path
- task id
- app artifact identity
- backend fixture state
- simulator/device identity
- evidence directory

Each validator returns JSON:

```json
{
  "taskId": "T01-record-selection-persistence-simulator",
  "passed": true,
  "oracle": "human-or-scripted",
  "observations": [],
  "failureReason": null
}
```
