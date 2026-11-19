# Eval report: smoke-1

- Run id `cd717335-6b2d-40cd-9ddc-c00a9c848953`, split `tune`, started 2026-11-19T09:40:51.267889+00:00.
- Items expected 2, finished 2, missing or errored 0 (each counts as a fail).
- Freeze hash: `not frozen (tune run)`.

Scope notes (stated before the run):
- D144: the POC walks only `printer-offline` and `pos-screen-frozen`. K8 is scored on the l1_guided tickets whose labelled runbooks include one of them; every other l1_guided ticket is excluded from K8 as `out_of_poc_scope` and ends in a handoff (`no_approved_steps`) by design.
- K1-K3 score the routing decision (Triage's route after Policy, D95); a ticket handed off only because its runbook has no approved steps keeps its L1 decision (D146).
- K8 walks use scripted approvals (`mock-l2`) and simulated L2 work, so K8 is not an autonomous fix rate; the store is a simulator answering from a fault card, with the outcome decided by code (D40, D58).
- The design notes (agent-check.md E1-E18) were written from all 256 tickets before the split; the history tools serve earlier tickets of the same store from both halves.

## KPIs

| KPI | Name | Value | Target | Meets | Eligible | Passed | Failed (missing) | Excluded | Tune |
|---|---|---|---|---|---|---|---|---|---|
| K1 | Routing accuracy (L1 vs L2) | 100.0% | >= 85% | yes | 2 | 2 | 0 (0) | - | - |
| K2 | Escalations caught | - | >= 95% | - | 0 | 0 | 0 (0) | - | - |
| K3 | Needless escalations | 0.0% | <= 15% | yes | 2 | 2 | 0 (0) | - | - |
| K5 | Right runbook walked | 100.0% | >= 90% | yes | 2 | 2 | 0 (0) | - | - |
| K6 | Right first action | 100.0% | >= 85% | yes | 2 | 2 | 0 (0) | - | - |
| K7 | Steps come from the runbook | 100.0% | >= 100% | yes | 1 | 1 | 0 (0) | no_steps_sent 1 | - |
| K8 | Fix matches the correct answer (D144 scope) | 100.0% | >= 80% | yes | 1 | 1 | 0 (0) | out_of_poc_scope 1 | - |
| K15a | L2 note mandatory fields | 100.0% | >= 100% | yes | 1 | 1 | 0 (0) | - | - |
| K15b | L2 note quality (judge) | - | >= 80% | - | 0 | 0 | 0 (0) | label_not_l2 1 | - |
| K15c | L1 pack quality (judge) | - | >= 80% | - | 0 | 0 | 0 (0) | - | - |

## By group

| KPI | A (POS, Printers) | B (other) | C (tricky slice) |
|---|---|---|---|
| K1 | 100.0% (2/2) | - | - |
| K2 | - | - | - |
| K3 | 0.0% (2/2) | - | - |
| K5 | 100.0% (2/2) | - | - |
| K6 | 100.0% (2/2) | - | - |
| K7 | 100.0% (1/1) | - | - |
| K8 | 100.0% (1/1) | - | - |
| K15a | 100.0% (1/1) | - | - |
| K15b | - | - | - |
| K15c | - | - | - |

## By category

| KPI | POS | Printers |
|---|---|---|
| K1 | 100.0% (1/1) | 100.0% (1/1) |
| K2 | - | - |
| K3 | 0.0% (1/1) | 0.0% (1/1) |
| K5 | 100.0% (1/1) | 100.0% (1/1) |
| K6 | 100.0% (1/1) | 100.0% (1/1) |

## K14 time and cost

- 2 finished tickets: tokens mean 61234, max 74222; cost mean $0.0041, total $0.01 (agent only; simulator and judge calls are on their own traces); wall time mean 50 s, max 64 s (includes simulated replies and approvals).

## Misses

Every failed item with its reason (gaps to explain).

