# K4 replay and retrieval ablation (tune half)

- kb_rev: `kb-910d4fe769154b9c`
- Tickets: 109 tune labelled tickets with a labelled runbook (INC-00246 lists none). Held-out is not run here (D39, S14).
- Query: masked subject + description (raw) or system version + subject + codes (device); `search_kb(doc_type=runbook)`, k = 5. Hit = any labelled runbook in the top N.
- Latency: ranking + section fetch in-process (no MCP hop, no query embedding: vectors are computed once per query before timing).

- Code test: `error <code>` with the code's device family, for every code in the KB error tables; a pass is a section holding the code as the top result.

| Setting | hit@1 | hit@3 | code on top | p50 ms | p95 ms | KB tokens / call | misses@3 |
|---|---|---|---|---|---|---|---|
| BM25 | 67.9% | 89.0% | 70/70 | 6.7 | 15.0 | 1002 | 12 |
| vector | 80.7% | 95.4% | 51/70 | 2.0 | 2.1 | 1012 | 5 |
| hybrid | 77.1% | 95.4% | 63/70 | 8.1 | 13.1 | 1079 | 5 |
| hybrid + code rule | 77.1% | 95.4% | 70/70 | 7.8 | 13.3 | 1079 | 5 |
| hybrid + code rule, family given | 79.8% | 95.4% | 70/70 | 9.3 | 24.5 | 1039 | 5 |
| hybrid + code rule, document-first | 79.8% | 95.4% | 70/70 | 7.8 | 13.1 | 1109 | 5 |
| hybrid + code rule, device query | 67.0% | 91.7% | 70/70 | 5.2 | 7.7 | 1062 | 9 |

**Chosen: hybrid + code rule**: the simplest setting with hit@3 >= 90% (95.4%) that also puts the code's section on top for every KB code (70/70) (D83).

Misses at 3: INC-00018, INC-00107, INC-00121, INC-00245, INC-00290
