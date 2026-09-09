# Active handoff

## Current task and acceptance
## Confirmed evidence / unresolved hypotheses
## Changed files and writer ownership
## Checks actually run and results
## Remaining work / next specific question
## Rollback and external actions requiring authorization

Keep this concise. Link detailed results instead of copying logs. Do not store credentials.

## Example (replace with evidence from your task)
- Task: R2, preserve tool definitions in upstream messages.
- Confirmed: fake runner captured no definitions; cause is request builder.
- Owner: one writer for request_builder.py; another task owns UI files.
- Changed: request_builder.py, test_request_builder.py.
- Verified: python -m unittest test_request_builder — 3 passed offline.
- Unverified: live provider behavior; next step is separately authorized acceptance.
- Rollback: revert only this patch; no storage migration.
