# Other safety suites (S14 step 8)

Run 2026-11-19 10:23Z.

| Suite | Result | Time | Last line |
|---|---|---|---|
| OPA policy tests | pass | 0 s | PASS: 107/107 |
| OPA rule-breaks (API) | pass | 19 s | 10/10 pass -> eval/reports/rule_breaks.md |
| itsm-actions rule-breaks and approvals | pass | 12 s |   warnings.warn(PytestDeprecationWarning(_DEFAULT_FIXTURE_LOOP_SCOPE_UNSET)) |
| Revision and resume (unit) | pass | 2 s |   warnings.warn(PytestDeprecationWarning(_DEFAULT_FIXTURE_LOOP_SCOPE_UNSET)) |
| SLA expiry during a pause, approval/timer race | pass | 73 s |   warnings.warn(PytestDeprecationWarning(_DEFAULT_FIXTURE_LOOP_SCOPE_UNSET)) |
| Branch safety (walk rules, unit) | pass | 2 s |   warnings.warn(PytestDeprecationWarning(_DEFAULT_FIXTURE_LOOP_SCOPE_UNSET)) |
| Branch safety and resume (live walks) | pass (live mode) | 35 s | 7 passed; in eval mode 2 fail by design: fault cards decide the outcome, so the scripted printer fix is "no change" |
| Safety checker seeded bad rows | pass | 2 s |   warnings.warn(PytestDeprecationWarning(_DEFAULT_FIXTURE_LOOP_SCOPE_UNSET)) |
| Abstention (20 tune tickets, family removed) | pass | 109 s | - Control found a runbook: **20/20**. |

- Secret leak (A24): runs inside `make safety-check` on every eval run.
- Revoked approval: not covered; the POC has no revoke action (open item).
- KB-fixture injection (15 cases): needs a test-only KB revision publish on an idle stack; not run in this pass.
