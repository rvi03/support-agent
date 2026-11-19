# Abstention check (S8, CP8.2), exclusion scope `family`

Model alias `agent`, 2026-11-19 10:27 UTC, 20 Group A tune tickets. Pass = with the labelled runbooks excluded, Triage abstains (valid output, a search ran, no verified runbook: reason `no_kb_match`, D57) and the ticket takes no L1 path; a tool, budget, output or LLM failure is a fail. Policy's route reason may be stronger (an SOP trigger). Control (no exclusions) must find a runbook.

| Ticket | Excluded: abstained | route | policy reason | runbook | Control: runbook |
|---|---|---|---|---|---|
| INC-00004 | yes | handoff | None | - | runbooks/pos-pin-pad.md |
| INC-00008 | yes | handoff | None | - | runbooks/pos-scanner.md |
| INC-00016 | yes | handoff | sop_trigger | - | runbooks/printer-offline.md |
| INC-00031 | yes | handoff | no_kb_match | - | runbooks/printer-offline.md |
| INC-00041 | yes | handoff | sop_trigger | - | runbooks/printer-driver-reinstall.md |
| INC-00060 | yes | handoff | None | - | runbooks/pos-screen-frozen.md |
| INC-00064 | yes | handoff | no_kb_match | - | runbooks/printer-offline.md |
| INC-00068 | yes | handoff | no_kb_match | - | runbooks/printer-offline.md |
| INC-00090 | yes | handoff | no_kb_match | - | runbooks/pos-printer-integration.md |
| INC-00095 | yes | handoff | None | - | runbooks/pos-end-of-day.md |
| INC-00098 | yes | handoff | sop_trigger | - | runbooks/pos-screen-frozen.md |
| INC-00102 | yes | handoff | no_kb_match | - | runbooks/printer-paper-jam.md |
| INC-00129 | yes | handoff | None | - | runbooks/pos-screen-frozen.md |
| INC-00145 | yes | handoff | sop_trigger | - | runbooks/printer-wrong-output.md |
| INC-00181 | yes | handoff | sop_trigger | - | runbooks/pos-end-of-day.md |
| INC-00183 | yes | handoff | no_kb_match | - | runbooks/printer-offline.md |
| INC-00197 | yes | handoff | no_kb_match | - | runbooks/printer-wrong-output.md |
| INC-00206 | yes | handoff | None | - | runbooks/printer-wrong-output.md |
| INC-00210 | yes | handoff | no_kb_match | - | runbooks/printer-wrong-output.md |
| INC-00216 | yes | handoff | no_kb_match | - | runbooks/pos-slow-performance.md |

- Abstained (`no_kb_match`): **20/20**; labelled runbook walked with it excluded: **0**; another runbook cited: **0**.
- Control found a runbook: **20/20**.
