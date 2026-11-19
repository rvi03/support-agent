# Tricky tickets on the tune half (S10, CP10.2), tricky-tune v2

Model alias `agent`, 2026-11-19 06:02 UTC, full graph (Enrich, Triage, Policy, Router, handler, gate, Communicate). Expected routes are hand judgements by the K9 rules (eval/tricky_tune.yaml). A Clarify run stops at the pause.

| Ticket | Type | Example | Expected | Agent route (rule) | Triage | Category | Reason | Pass |
|---|---|---|---|---|---|---|---|---|
| INC-00149 | vague | yes | clarify | clarify (4) | clarify | POS | None | yes |
| INC-00189 | vague |  | clarify | clarify (4) | clarify | Soft Serve | None | yes |
| INC-00307 | vague |  | resolver, handoff | resolver (6) | l1_guided | POS | resolver_not_built | yes |
| INC-00005 | misdirection | yes | redirect | redirect (3) | non_it | Other | None | yes |
| INC-00127 | misdirection |  | resolver | resolver (6) | l1_guided | Printers | resolver_not_built | yes |
| INC-00279 | misdirection |  | handoff, resolver | resolver (6) | l1_then_l2 | Printers | resolver_not_built | yes |
| INC-00014 | unknown_system |  | human | human (2) | human | Soft Serve | unknown_system | yes |
| INC-00035 | contradictory |  | resolver, handoff | resolver (6) | l1_then_l2 | POS | resolver_not_built | yes |
| INC-00059 | contradictory |  | resolver | resolver (6) | l1_guided | Printers | resolver_not_built | yes |
| INC-00054 | miscategorized | yes | handoff | handoff (1) | l1_then_l2 | Wi-Fi / Network | sop_trigger | yes |
| INC-00242 | miscategorized |  | handoff, l1_pack | l1_pack (7) | l1_guided | Wi-Fi / Network | None | yes |

- Expected route: **11/11**; without the few-shot examples 8/8.
- Per type: contradictory 2/2; miscategorized 2/2; misdirection 3/3; unknown_system 1/1; vague 3/3
- Tokens per ticket mean 35206.

