# OPA rule-break suite (API)

Probe ticket `SWT-3AF3E0F1A99D` (paused at `5bc43a3f-b28c-45bd-83a0-f783176ec7b7`); pass = expected status and, for a rule on the ticket, a `denied` audit event.

| Probe | Status | Expected | Audited | Result |
|---|---|---|---|---|
| P1 other store reads the ticket | 404 | (404,) | yes | pass |
| P1 other store replies | 404 | (404,) | yes | pass |
| P3 store user approves | 403 | (403,) | yes | pass |
| P2 L2 replies as the store | 404 | (403, 404) | yes | pass |
| P4 vendor approves a store pause | 404 | (403, 404, 409) | yes | pass |
| P2 L1 approves | 404 | (403, 404, 409) | yes | pass |
| D53 stale pending id | 409 | (409,) | yes | pass |
| D52 store sends replay fields | 422 | (422,) | n/a | pass |
| 401 no token | 401 | (401,) | n/a | pass |
| 413 oversized reply | 413 | (413, 422) | n/a | pass |

**10 of 10 pass.**

itsm-actions rules (run_fix binding, approvals, autonomy, closed ticket, deadline) are in tests/integration/test_itsm.py; policies in `make opa-test`.
