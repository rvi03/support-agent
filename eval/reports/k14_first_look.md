# K14 first look: time and cost per ticket (S10, CP10.5)

2026-11-19 06:31 UTC; the 40 model-check tune tickets through the full graph, 4 at a time, model alias `agent` (gpt-6-luna). Before S11: the Resolver is a stub, so a Group A walk is not in these numbers yet.

| Measure | mean / p50 / p95 / max |
|---|---|
| Wall time per ticket, s (agent clock) | 25.4 / 24.4 / 38.8 / 41.6 |
| Trace time per ticket, s (Langfuse, first to last span) | 25.4 / 24.4 / 38.8 / 41.6 |
| Cost per ticket, USD (Langfuse generations) | 0.0021 / 0.0022 / 0.0029 / 0.0031 |
| Cost per ticket, USD (agent's counter, LiteLLM header) | 0.0021 / 0.0022 / 0.0029 / 0.0031 |
| Tokens per ticket | 47267 / 46806 / 52198 / 53732 |
| LLM calls per ticket | 4.2 / 4.0 / 5.0 / 5.0 |

- Tickets run: 40/40; traces found: 40/40.
- Total cost of the 40 (Langfuse): $0.0826; agent counter $0.0826.
- Tickets with LLM calls but $0 cost: 0.
- Target: set in S14 from run 1 (kpis.md K14); the token budget per ticket is 120k (D104).

