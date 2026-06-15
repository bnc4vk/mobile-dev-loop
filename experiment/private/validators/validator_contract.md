# Validator Contract

Validators must be deterministic and independent from agent self-reported success.

Each validator receives:

- run manifest path
- task id
- app artifact identity
- backend fixture state
- simulator/device identity
- evidence directory

For simulator tasks, validators install the exact final artifact produced by the agent and drive the required runtime transitions without rebuilding the app. Evaluator-side validation evidence is stored separately from agent execution metrics in `mobile-validation.json` and `validation-evidence/`.

Candidate runs may be assessed from the `mobile-dev` ledger. Baseline runs must not be required to emit the candidate ledger and can be assessed from reconstructed artifact/evidence provenance plus the independent mobile oracle.

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
