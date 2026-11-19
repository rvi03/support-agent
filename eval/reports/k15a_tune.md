# K15a on the 40 model-check tune tickets (S10, CP10.6)

2026-11-19 06:31 UTC, full graph, model alias `agent`. Checker: eval/k15a.py (independent of the agent, D42). The Resolver is a stub until S11, so Group A L1 tickets also hand off (`resolver_not_built`).

| Ticket | Route | Reason | Note source | Note K15a | Fallback K15a | Problems |
|---|---|---|---|---|---|---|
| INC-00004 | resolver | resolver_not_built | fallback | yes | yes | - |
| INC-00008 | resolver | resolver_not_built | llm | yes | yes | - |
| INC-00016 | resolver | resolver_not_built | fallback | yes | yes | - |
| INC-00031 | resolver | resolver_not_built | llm | yes | yes | - |
| INC-00041 | resolver | resolver_not_built | llm | yes | yes | - |
| INC-00060 | resolver | resolver_not_built | llm | yes | yes | - |
| INC-00064 | resolver | resolver_not_built | llm | yes | yes | - |
| INC-00068 | resolver | resolver_not_built | llm | yes | yes | - |
| INC-00090 | resolver | resolver_not_built | llm | yes | yes | - |
| INC-00095 | resolver | resolver_not_built | llm | yes | yes | - |
| INC-00098 | resolver | resolver_not_built | llm | yes | yes | - |
| INC-00102 | resolver | resolver_not_built | llm | yes | yes | - |
| INC-00129 | resolver | resolver_not_built | llm | yes | yes | - |
| INC-00145 | handoff | sop_trigger | llm | yes | yes | - |
| INC-00181 | resolver | resolver_not_built | llm | yes | yes | - |
| INC-00183 | resolver | resolver_not_built | fallback | yes | yes | - |
| INC-00197 | resolver | resolver_not_built | llm | yes | yes | - |
| INC-00206 | resolver | resolver_not_built | llm | yes | yes | - |
| INC-00210 | resolver | resolver_not_built | llm | yes | yes | - |
| INC-00216 | resolver | resolver_not_built | llm | yes | yes | - |
| INC-00100 | l1_pack | - | - | no note | yes | - |
| INC-00141 | l1_pack | - | - | no note | yes | - |
| INC-00257 | l1_pack | - | - | no note | yes | - |
| INC-00259 | handoff | sop_trigger | llm | yes | yes | - |
| INC-00262 | l1_pack | - | - | no note | yes | - |
| INC-00020 | handoff | sop_trigger | llm | yes | yes | - |
| INC-00023 | l1_pack | - | - | no note | yes | - |
| INC-00028 | handoff | sop_trigger | llm | yes | yes | - |
| INC-00043 | handoff | l2_needed | llm | yes | yes | - |
| INC-00069 | l1_pack | - | - | no note | yes | - |
| INC-00017 | l1_pack | - | - | no note | yes | - |
| INC-00021 | l1_pack | - | - | no note | yes | - |
| INC-00053 | l1_pack | - | - | no note | yes | - |
| INC-00074 | clarify | - | - | no note | yes | - |
| INC-00078 | handoff | sop_trigger | llm | yes | yes | - |
| INC-00006 | handoff | sop_trigger | llm | yes | yes | - |
| INC-00012 | handoff | sop_trigger | llm | yes | yes | - |
| INC-00013 | handoff | sop_trigger | llm | yes | yes | - |
| INC-00034 | handoff | sop_trigger | fallback | yes | yes | - |
| INC-00051 | l1_pack | - | - | no note | yes | - |

- L2 notes stored: 29; pass K15a: **29/29** (target 100%).
- Code-built fallback note for every ticket: **40/40** pass.
- Runs failed: 0 (a failed run counts as a fail, D56).

