# Model check (S8, CP8.4)

40 fixed tune-half tickets (eval/model_check.json: 20 Group A, 20 mixed); Enrich -> Triage -> Policy -> Router; K1 counts handoff and human as L2, and a Resolver or L1-pack ticket that Triage routed l1_then_l2 as L2 too (it walks the runbook first, then hands off by design); every other route is L1. K5 over the L1-labelled tickets with a labelled runbook.

## `agent` (2026-11-19 02:28 UTC)

- K1 routing L1/L2: **95.0% (38/40)** (target >= 85%)
- K5 right runbook (L1-routed labelled tickets with a runbook): **100.0% (18/18)** (target >= 90%)
- Structured output valid: **100.0% (40/40)**; valid on the first try: 100.0% (40/40)
- Latency p50 9.4 s, max 15.0 s; tokens per ticket mean 29276, max 42168; LLM calls mean 3.2
- Rule X1: pass (K1 >= 85% and invalid output <= 5%)

| Ticket | Label | Agent | Handoff reason | Runbook | Quote check | Tools | Tokens | s | Model triggers | Conflicts |
|---|---|---|---|---|---|---|---|---|---|---|
| INC-00004 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/pos-pin-pad.md | verified | 3 | 25992 | 8.7 | - | - |
| INC-00008 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/pos-scanner.md | verified | 3 | 38082 | 11.3 | - | - |
| INC-00016 | L2 | L2 (resolver, line 6, l1_then_l2) | - | runbooks/printer-offline.md | verified | 3 | 27895 | 9.9 | - | - |
| INC-00031 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/printer-offline.md | verified | 2 | 26046 | 8.7 | - | - |
| INC-00041 | L2 | L2 (resolver, line 6, l1_then_l2) | - | runbooks/printer-driver-reinstall.md | verified | 3 | 28239 | 9.4 | - | - |
| INC-00060 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/pos-screen-frozen.md | verified | 3 | 26279 | 8.6 | - | - |
| INC-00064 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/printer-offline.md | verified | 3 | 27734 | 9.0 | - | - |
| INC-00068 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/printer-offline.md | verified | 3 | 26745 | 8.9 | - | - |
| INC-00090 | L2 | L2 (resolver, line 6, l1_then_l2) | - | runbooks/printer-offline.md | verified | 3 | 27245 | 8.5 | - | - |
| INC-00095 | L2 | L1 (resolver, line 6, l1_guided) | - | runbooks/pos-end-of-day.md | verified | 3 | 27008 | 10.3 | - | - |
| INC-00098 | L2 | L2 (resolver, line 6, l1_then_l2) | - | runbooks/pos-screen-frozen.md | verified | 3 | 27663 | 9.5 | - | - |
| INC-00102 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/printer-paper-jam.md | verified | 2 | 24552 | 8.5 | - | - |
| INC-00129 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/pos-screen-frozen.md | verified | 3 | 38258 | 11.0 | - | - |
| INC-00145 | L2 | L2 (handoff, line 1, l1_then_l2) | sop_trigger | runbooks/pos-printer-integration.md | verified | 3 | 27531 | 9.1 | customer_waited_30_min: Approximately 250+ customers affected since 08:45 this morni | - |
| INC-00181 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/pos-end-of-day.md | verified | 3 | 25447 | 8.8 | - | - |
| INC-00183 | L2 | L2 (handoff, line 1, l1_then_l2) | sop_trigger | runbooks/printer-offline.md | verified | 3 | 42168 | 15.0 | error_not_in_kb: error code E-PRINT-502 ('Printer communication timeout') | - |
| INC-00197 | L2 | L2 (resolver, line 6, l1_then_l2) | - | runbooks/printer-wrong-output.md | verified | 3 | 26919 | 9.1 | - | - |
| INC-00206 | L2 | L2 (resolver, line 6, l1_then_l2) | - | runbooks/printer-wrong-output.md | verified | 3 | 27306 | 8.8 | - | - |
| INC-00210 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/printer-wrong-output.md | verified | 3 | 26322 | 8.6 | - | - |
| INC-00216 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/pos-slow-performance.md | verified | 2 | 24555 | 9.1 | - | - |
| INC-00100 | L1 | L1 (l1_pack, line 7, l1_guided) | - | runbooks/kiosk-frozen.md | verified | 2 | 23899 | 11.6 | - | - |
| INC-00141 | L1 | L1 (l1_pack, line 7, l1_guided) | - | runbooks/kiosk-frozen.md | verified | 3 | 34293 | 11.0 | - | - |
| INC-00257 | L1 | L1 (l1_pack, line 7, l1_guided) | - | runbooks/kiosk-touchscreen.md | verified | 2 | 24044 | 8.5 | - | - |
| INC-00259 | L2 | L2 (handoff, line 1, l2_now) | sop_trigger | runbooks/kiosk-payment-reader.md | verified | 2 | 24781 | 9.3 | payment_failure: Customers are unable to complete transactions; error_not_in_kb: displaying an error code E-402; customer_asks: Customers are unable to complete transactions and the kiosk  | - |
| INC-00262 | L1 | L1 (l1_pack, line 7, l1_guided) | - | runbooks/kiosk-software-crash.md | verified | 3 | 24724 | 13.1 | - | - |
| INC-00020 | L2 | L2 (handoff, line 1, l1_then_l2) | sop_trigger | runbooks/online-orders-not-on-kds.md | verified | 3 | 38381 | 11.8 | third_party_integration_failure: The issue persists across all three online delivery partner  | - |
| INC-00023 | L2 | L2 (l1_pack, line 7, l1_then_l2) | - | runbooks/online-orders-sync-failure.md | verified | 3 | 26311 | 9.4 | - | - |
| INC-00028 | L2 | L2 (handoff, line 1, l1_then_l2) | sop_trigger | runbooks/online-orders-aggregator-disconnect.md | verified | 3 | 38186 | 12.9 | third_party_integration_failure: The Zomato integration on our NetLink router has been offlin | - |
| INC-00043 | L2 | L2 (handoff, line 1, l1_guided) | sop_trigger | runbooks/online-orders-sync-failure.md | verified | 2 | 26011 | 8.4 | customer_asks: Need urgent fix. | - |
| INC-00069 | L2 | L2 (handoff, line 1, l1_then_l2) | sop_trigger | runbooks/online-orders-sync-failure.md | verified | 3 | 36506 | 12.9 | customer_asks: Need urgent fix as we're losing orders. | - |
| INC-00017 | L1 | L1 (l1_pack, line 7, l1_guided) | - | runbooks/soft-serve-overcooling.md | verified | 2 | 24687 | 8.6 | - | - |
| INC-00021 | L1 | L1 (l1_pack, line 7, l1_guided) | - | runbooks/soft-serve-overcooling.md | verified | 2 | 24518 | 8.6 | - | - |
| INC-00053 | L2 | L2 (handoff, line 8, l2_now) | - | - | - | 2 | 25854 | 10.0 | - | - |
| INC-00074 | L1 | L1 (l1_pack, line 7, l1_guided) | - | runbooks/soft-serve-error-codes.md | verified | 3 | 27135 | 11.0 | - | - |
| INC-00078 | L2 | L2 (handoff, line 1, l1_then_l2) | sop_trigger | runbooks/soft-serve-error-codes.md | verified | 3 | 40594 | 11.5 | error_not_in_kb: displaying error code E-447; customer_waited_30_min: started showing the error around 3:45 PM during the afternoo | - |
| INC-00006 | L2 | L1 (l1_pack, line 7, l1_guided) | - | runbooks/network-guest-wifi.md | verified | 3 | 26185 | 9.0 | - | - |
| INC-00012 | L2 | L2 (handoff, line 1, l1_then_l2) | sop_trigger | runbooks/network-router-offline.md | verified | 3 | 39649 | 11.6 | network_failure: all POS terminals lose network access; customer_asks: We need this escalated for immediate investigation of potent | - |
| INC-00013 | L2 | L2 (handoff, line 1, l1_guided) | sop_trigger | runbooks/network-slow.md | verified | 3 | 26143 | 9.6 | network_failure: Multiple customer and staff devices unable to obtain IP addr | - |
| INC-00034 | L2 | L2 (handoff, line 1, l2_now) | sop_trigger | - | - | 3 | 39875 | 11.5 | network_failure: The network drops occur approximately every 15-25 minutes, l; customer_asks: We need immediate diagnostics and potential hardware replace | - |
| INC-00051 | L2 | L2 (handoff, line 1, l1_then_l2) | sop_trigger | runbooks/network-vpn.md | verified | 3 | 27295 | 9.7 | network_failure: The VPN drops approximately every 15–20 minutes for 2–3 minu | - |

## `agent-terra` (2026-11-19 02:31 UTC)

- K1 routing L1/L2: **77.5% (31/40)** (target >= 85%)
- K5 right runbook (L1-routed labelled tickets with a runbook): **94.4% (17/18)** (target >= 90%)
- Structured output valid: **100.0% (40/40)**; valid on the first try: 100.0% (40/40)
- Latency p50 11.5 s, max 19.1 s; tokens per ticket mean 28895, max 57033; LLM calls mean 3.2
- Rule X1: FAIL (K1 >= 85% and invalid output <= 5%)

| Ticket | Label | Agent | Handoff reason | Runbook | Quote check | Tools | Tokens | s | Model triggers | Conflicts |
|---|---|---|---|---|---|---|---|---|---|---|
| INC-00004 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/pos-pin-pad.md | verified | 2 | 25729 | 11.4 | - | - |
| INC-00008 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/pos-scanner.md | verified | 2 | 25679 | 11.2 | - | - |
| INC-00016 | L2 | L2 (handoff, line 1, l2_now) | sop_trigger | runbooks/printer-offline.md | verified | 4 | 57033 | 17.6 | error_not_in_kb: all print jobs are being rejected with error code ERR-P502 | - |
| INC-00031 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/printer-offline.md | verified | 2 | 26009 | 11.2 | - | - |
| INC-00041 | L2 | L2 (handoff, line 1, l2_now) | sop_trigger | runbooks/printer-driver-reinstall.md | verified | 3 | 43460 | 15.5 | error_not_in_kb: error code 0x00000050 | - |
| INC-00060 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/pos-screen-frozen.md | verified | 2 | 26192 | 10.8 | - | - |
| INC-00064 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/pos-printer-integration.md | verified | 3 | 26984 | 13.1 | - | - |
| INC-00068 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/printer-offline.md | verified | 2 | 26445 | 10.3 | - | - |
| INC-00090 | L2 | L1 (resolver, line 6, l1_guided) | - | runbooks/printer-offline.md | verified | 2 | 26889 | 12.1 | - | - |
| INC-00095 | L2 | L1 (resolver, line 6, l1_guided) | - | runbooks/pos-end-of-day.md | verified | 2 | 26259 | 11.3 | - | - |
| INC-00098 | L2 | L1 (resolver, line 6, l1_guided) | - | runbooks/pos-screen-frozen.md | verified | 2 | 27532 | 10.4 | - | - |
| INC-00102 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/printer-paper-jam.md | verified | 2 | 24438 | 11.1 | - | - |
| INC-00129 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/pos-screen-frozen.md | verified | 3 | 26521 | 13.5 | - | - |
| INC-00145 | L2 | L2 (human, line 2, human) | - | runbooks/printer-wrong-output.md | verified | 3 | 27283 | 13.0 | - | - |
| INC-00181 | L1 | L2 (resolver, line 6, l1_then_l2) | - | runbooks/pos-end-of-day.md | verified | 3 | 26025 | 11.4 | - | - |
| INC-00183 | L2 | L2 (handoff, line 1, l2_now) | sop_trigger | runbooks/printer-offline.md | verified | 3 | 46395 | 14.1 | error_not_in_kb: error code E-PRINT-502 ('Printer communication timeout') | - |
| INC-00197 | L2 | L2 (resolver, line 6, l1_then_l2) | - | runbooks/printer-wrong-output.md | verified | 3 | 26733 | 11.1 | - | - |
| INC-00206 | L2 | L2 (resolver, line 6, l1_then_l2) | - | runbooks/printer-wrong-output.md | verified | 2 | 27140 | 11.5 | - | - |
| INC-00210 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/printer-wrong-output.md | verified | 2 | 25947 | 10.2 | - | - |
| INC-00216 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/pos-slow-performance.md | verified | 2 | 24662 | 10.9 | - | - |
| INC-00100 | L1 | L1 (l1_pack, line 7, l1_guided) | - | runbooks/kiosk-frozen.md | verified | 2 | 23523 | 10.2 | - | - |
| INC-00141 | L1 | L1 (l1_pack, line 7, l1_guided) | - | runbooks/kiosk-frozen.md | verified | 2 | 23875 | 11.2 | - | - |
| INC-00257 | L1 | L1 (l1_pack, line 7, l1_guided) | - | runbooks/kiosk-touchscreen.md | verified | 2 | 24037 | 10.3 | - | - |
| INC-00259 | L2 | L2 (handoff, line 1, l2_now) | sop_trigger | runbooks/kiosk-payment-reader.md | verified | 4 | 52595 | 19.1 | error_not_in_kb: displaying an error code E-402 whenever customers attempt to | - |
| INC-00262 | L1 | L2 (human, line 2, human) | - | runbooks/kiosk-software-crash.md | verified | 3 | 24913 | 13.4 | - | - |
| INC-00020 | L2 | L2 (l1_pack, line 7, l1_then_l2) | - | runbooks/online-orders-sync-failure.md | verified | 4 | 30396 | 12.7 | - | - |
| INC-00023 | L2 | L1 (l1_pack, line 7, l1_guided) | - | runbooks/online-orders-sync-failure.md | verified | 3 | 26294 | 11.7 | - | - |
| INC-00028 | L2 | L2 (handoff, line 1, l2_now) | sop_trigger | runbooks/online-orders-aggregator-disconnect.md | verified | 3 | 26427 | 13.8 | third_party_integration_failure: The Zomato integration on our NetLink router has been offlin | - |
| INC-00043 | L2 | L2 (human, line 2, human) | - | - | - | 2 | 26018 | 10.8 | - | - |
| INC-00069 | L2 | L2 (human, line 2, human) | - | - | - | 2 | 24925 | 10.4 | - | - |
| INC-00017 | L1 | L1 (l1_pack, line 7, l1_guided) | - | runbooks/soft-serve-overcooling.md | verified | 3 | 25095 | 11.8 | - | - |
| INC-00021 | L1 | L2 (human, line 2, human) | - | - | - | 3 | 24963 | 12.4 | - | - |
| INC-00053 | L2 | L2 (human, line 2, human) | - | - | - | 2 | 26056 | 12.1 | - | - |
| INC-00074 | L1 | L1 (l1_pack, line 7, l1_guided) | - | runbooks/soft-serve-error-codes.md | verified | 3 | 27410 | 13.1 | - | - |
| INC-00078 | L2 | L2 (handoff, line 1, l2_now) | sop_trigger | runbooks/soft-serve-error-codes.md | verified | 4 | 43055 | 18.8 | error_not_in_kb: The soft serve ice cream machine at the Worli location is di | - |
| INC-00006 | L2 | L1 (l1_pack, line 7, l1_guided) | - | runbooks/network-guest-wifi.md | verified | 2 | 25790 | 14.5 | - | - |
| INC-00012 | L2 | L2 (handoff, line 1, l2_now) | sop_trigger | runbooks/network-router-offline.md | verified | 2 | 26891 | 13.4 | network_failure: The router (NetLink NL-3000 v2.2, asset RTR-0034-01) drops i; payment_failure: During these outages, all POS terminals lose network access,; customer_asks: We need this escalated for immediate investigation of potent | - |
| INC-00013 | L2 | L1 (l1_pack, line 7, l1_guided) | - | runbooks/network-slow.md | verified | 2 | 25914 | 11.2 | - | - |
| INC-00034 | L2 | L2 (human, line 2, human) | - | - | - | 3 | 27463 | 11.1 | - | - |
| INC-00051 | L2 | L2 (l1_pack, line 7, l1_then_l2) | - | runbooks/network-vpn.md | verified | 2 | 26805 | 10.9 | - | - |

## `agent` (2026-11-19 03:41 UTC)

- K1 routing L1/L2: **85.0% (34/40)** (target >= 85%)
- K5 right runbook (L1-routed labelled tickets with a runbook): **94.4% (17/18)** (target >= 90%)
- Structured output valid: **100.0% (40/40)**; valid on the first try: 100.0% (40/40)
- Latency p50 10.9 s, max 18.3 s; tokens per ticket mean 29245, max 51796; LLM calls mean 3.3
- Rule X1: pass (K1 >= 85% and invalid output <= 5%)

| Ticket | Label | Agent | Handoff reason | Runbook | Quote check | Tools | Tokens | s | Model triggers | Conflicts |
|---|---|---|---|---|---|---|---|---|---|---|
| INC-00004 | L1 | L2 (handoff, line 1, l1_guided) | sop_trigger | runbooks/pos-pin-pad.md | verified | 3 | 26081 | 10.9 | payment_failure: Card transactions are pending. | - |
| INC-00008 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/pos-scanner.md | verified | 2 | 25921 | 10.6 | - | - |
| INC-00016 | L2 | L2 (resolver, line 6, l1_then_l2) | - | runbooks/printer-offline.md | verified | 2 | 26998 | 10.8 | - | - |
| INC-00031 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/printer-offline.md | verified | 2 | 38072 | 17.0 | - | - |
| INC-00041 | L2 | L2 (handoff, line 1, l1_then_l2) | sop_trigger | runbooks/printer-driver-reinstall.md | verified | 3 | 27973 | 9.6 | customer_asks: A full driver reinstallation is required to restore function | - |
| INC-00060 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/pos-screen-frozen.md | verified | 2 | 25665 | 8.7 | - | - |
| INC-00064 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/pos-printer-integration.md | verified | 3 | 26441 | 9.9 | - | - |
| INC-00068 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/printer-offline.md | verified | 2 | 25808 | 9.2 | - | - |
| INC-00090 | L2 | L2 (resolver, line 6, l1_then_l2) | - | runbooks/printer-offline.md | verified | 3 | 39461 | 16.3 | - | - |
| INC-00095 | L2 | L2 (resolver, line 6, l1_then_l2) | - | runbooks/pos-end-of-day.md | verified | 4 | 26961 | 12.1 | - | - |
| INC-00098 | L2 | L2 (resolver, line 6, l1_then_l2) | - | runbooks/pos-screen-frozen.md | verified | 3 | 27560 | 11.5 | - | - |
| INC-00102 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/printer-paper-jam.md | verified | 2 | 24159 | 9.8 | - | - |
| INC-00129 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/pos-screen-frozen.md | verified | 3 | 37971 | 14.5 | - | - |
| INC-00145 | L2 | L2 (handoff, line 1, l1_then_l2) | sop_trigger | runbooks/pos-printer-integration.md | verified | 2 | 26741 | 10.4 | customer_waited_30_min: Approximately 250+ customers affected since 08:45 this morni | - |
| INC-00181 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/pos-end-of-day.md | verified | 2 | 25366 | 10.5 | - | - |
| INC-00183 | L2 | L2 (resolver, line 6, l1_then_l2) | - | runbooks/printer-offline.md | verified | 3 | 27950 | 9.9 | - | - |
| INC-00197 | L2 | L2 (resolver, line 6, l1_then_l2) | - | runbooks/printer-wrong-output.md | verified | 3 | 37913 | 13.9 | - | - |
| INC-00206 | L2 | L2 (handoff, line 1, l1_then_l2) | sop_trigger | runbooks/printer-wrong-output.md | verified | 4 | 27772 | 10.9 | customer_asks: Request urgent attention. | - |
| INC-00210 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/printer-wrong-output.md | verified | 3 | 37110 | 12.8 | - | - |
| INC-00216 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/pos-slow-performance.md | verified | 2 | 24402 | 8.9 | - | - |
| INC-00100 | L1 | L1 (l1_pack, line 7, l1_guided) | - | runbooks/kiosk-frozen.md | verified | 3 | 23855 | 13.7 | - | - |
| INC-00141 | L1 | L2 (l1_pack, line 7, l1_then_l2) | - | runbooks/kiosk-frozen.md | verified | 3 | 24134 | 10.2 | - | - |
| INC-00257 | L1 | L1 (l1_pack, line 7, l1_guided) | - | runbooks/kiosk-touchscreen.md | verified | 2 | 24080 | 9.2 | - | - |
| INC-00259 | L2 | L1 (l1_pack, line 7, l1_guided) | - | runbooks/kiosk-payment-reader.md | verified | 3 | 23879 | 14.9 | - | - |
| INC-00262 | L1 | L2 (human, line 2, human) | - | - | - | 3 | 24853 | 13.8 | - | - |
| INC-00020 | L2 | L2 (handoff, line 1, l1_then_l2) | sop_trigger | runbooks/online-orders-not-on-kds.md | verified | 2 | 26293 | 11.5 | third_party_integration_failure: The issue persists across all three online delivery partner  | - |
| INC-00023 | L2 | L2 (handoff, line 1, l1_guided) | no_kb_match | - | wrong_device_family | 3 | 26258 | 9.5 | - | - |
| INC-00028 | L2 | L2 (handoff, line 1, l2_now) | sop_trigger | - | wrong_device_family | 3 | 26224 | 11.6 | third_party_integration_failure: The Zomato integration on our NetLink router has been offlin | - |
| INC-00043 | L2 | L2 (handoff, line 1, l1_then_l2) | no_kb_match | - | - | 4 | 51796 | 18.3 | - | - |
| INC-00069 | L2 | L2 (handoff, line 1, l1_then_l2) | sop_trigger | - | - | 2 | 24850 | 10.0 | customer_asks: Need urgent fix as we're losing orders. | - |
| INC-00017 | L1 | L1 (l1_pack, line 7, l1_guided) | - | runbooks/soft-serve-overcooling.md | verified | 3 | 24972 | 10.8 | - | - |
| INC-00021 | L1 | L1 (l1_pack, line 7, l1_guided) | - | runbooks/soft-serve-overcooling.md | verified | 3 | 46058 | 17.4 | - | - |
| INC-00053 | L2 | L2 (handoff, line 8, l2_now) | - | - | - | 2 | 25683 | 9.8 | - | - |
| INC-00074 | L1 | L2 (human, line 2, human) | - | runbooks/soft-serve-error-codes.md | verified | 3 | 26785 | 10.7 | - | - |
| INC-00078 | L2 | L2 (handoff, line 1, human) | sop_trigger | runbooks/soft-serve-error-codes.md | verified | 2 | 27044 | 10.9 | error_not_in_kb: The error persists even after a standard power cycle attempt | - |
| INC-00006 | L2 | L1 (l1_pack, line 7, l1_guided) | - | runbooks/network-guest-wifi.md | verified | 2 | 25731 | 9.5 | - | - |
| INC-00012 | L2 | L2 (handoff, line 1, l2_now) | sop_trigger | - | - | 3 | 27035 | 13.5 | payment_failure: all POS terminals lose network access, preventing order proc; full_pos_outage: all POS terminals lose network access, preventing order proc; customer_asks: We need this escalated for immediate investigation of potent | - |
| INC-00013 | L2 | L2 (handoff, line 1, l1_then_l2) | sop_trigger | runbooks/network-slow.md | verified | 3 | 37932 | 13.3 | network_failure: Multiple customer and staff devices unable to obtain IP addr | - |
| INC-00034 | L2 | L2 (handoff, line 8, l2_now) | - | - | - | 3 | 27359 | 11.9 | - | - |
| INC-00051 | L2 | L2 (handoff, line 1, l1_then_l2) | sop_trigger | runbooks/network-vpn.md | verified | 3 | 38663 | 12.6 | network_failure: The VPN drops approximately every 15–20 minutes for 2–3 minu | - |

## `agent` (2026-11-19 04:10 UTC)

- K1 routing L1/L2: **87.5% (35/40)** (target >= 85%)
- K5 right runbook (L1-routed labelled tickets with a runbook): **100.0% (18/18)** (target >= 90%)
- Structured output valid: **100.0% (40/40)**; valid on the first try: 100.0% (40/40)
- Latency p50 10.4 s, max 15.7 s; tokens per ticket mean 41611, max 46250; LLM calls mean 3.0
- Rule X1: pass (K1 >= 85% and invalid output <= 5%)

| Ticket | Label | Agent | Handoff reason | Runbook | Quote check | Tools | Tokens | s | Model triggers | Conflicts |
|---|---|---|---|---|---|---|---|---|---|---|
| INC-00004 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/pos-pin-pad.md | verified | 2 | 41199 | 12.5 | - | - |
| INC-00008 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/pos-scanner.md | verified | 2 | 41520 | 12.4 | - | - |
| INC-00016 | L2 | L2 (resolver, line 6, l1_then_l2) | - | runbooks/printer-offline.md | verified | 2 | 42866 | 12.3 | - | - |
| INC-00031 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/printer-offline.md | verified | 2 | 41172 | 12.0 | - | - |
| INC-00041 | L2 | L2 (resolver, line 6, l1_then_l2) | - | runbooks/printer-driver-reinstall.md | verified | 2 | 43442 | 9.6 | - | - |
| INC-00060 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/pos-screen-frozen.md | verified | 2 | 41701 | 9.2 | - | - |
| INC-00064 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/printer-offline.md | verified | 2 | 42552 | 8.6 | - | - |
| INC-00068 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/printer-offline.md | verified | 2 | 41652 | 10.5 | - | - |
| INC-00090 | L2 | L2 (resolver, line 6, l1_then_l2) | - | runbooks/pos-printer-integration.md | verified | 2 | 41749 | 9.7 | - | - |
| INC-00095 | L2 | L2 (resolver, line 6, l1_then_l2) | - | runbooks/pos-end-of-day.md | verified | 2 | 41977 | 10.1 | - | - |
| INC-00098 | L2 | L2 (resolver, line 6, l1_then_l2) | - | runbooks/pos-screen-frozen.md | verified | 2 | 42951 | 12.4 | - | - |
| INC-00102 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/printer-paper-jam.md | verified | 2 | 39929 | 10.5 | - | - |
| INC-00129 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/pos-screen-frozen.md | verified | 2 | 41484 | 8.8 | - | - |
| INC-00145 | L2 | L2 (resolver, line 6, l1_then_l2) | - | runbooks/printer-wrong-output.md | verified | 3 | 46250 | 10.2 | - | - |
| INC-00181 | L1 | L2 (resolver, line 6, l1_then_l2) | - | runbooks/pos-end-of-day.md | verified | 2 | 41472 | 10.6 | - | - |
| INC-00183 | L2 | L2 (resolver, line 6, l1_then_l2) | - | runbooks/printer-offline.md | verified | 2 | 43428 | 9.1 | - | - |
| INC-00197 | L2 | L2 (resolver, line 6, l1_then_l2) | - | runbooks/printer-wrong-output.md | verified | 2 | 42006 | 13.4 | - | - |
| INC-00206 | L2 | L2 (resolver, line 6, l1_then_l2) | - | runbooks/printer-wrong-output.md | verified | 2 | 42279 | 11.1 | - | - |
| INC-00210 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/printer-wrong-output.md | verified | 2 | 41202 | 8.3 | - | - |
| INC-00216 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/pos-slow-performance.md | verified | 2 | 40353 | 8.6 | - | - |
| INC-00100 | L1 | L1 (l1_pack, line 7, l1_guided) | - | runbooks/kiosk-frozen.md | verified | 2 | 39162 | 9.5 | - | - |
| INC-00141 | L1 | L1 (l1_pack, line 7, l1_guided) | - | runbooks/kiosk-frozen.md | verified | 2 | 39474 | 9.1 | - | - |
| INC-00257 | L1 | L1 (l1_pack, line 7, l1_guided) | - | runbooks/kiosk-touchscreen.md | verified | 2 | 39710 | 9.0 | - | - |
| INC-00259 | L2 | L2 (handoff, line 1, l2_now) | sop_trigger | runbooks/kiosk-payment-reader.md | verified | 2 | 39013 | 8.6 | error_not_in_kb: displaying an error code E-402 whenever customers attempt to | - |
| INC-00262 | L1 | L1 (l1_pack, line 7, l1_guided) | - | runbooks/kiosk-software-crash.md | verified | 2 | 40428 | 11.8 | - | - |
| INC-00020 | L2 | L2 (l1_pack, line 7, l1_then_l2) | - | runbooks/online-orders-sync-failure.md | verified | 2 | 42144 | 13.4 | - | - |
| INC-00023 | L2 | L2 (handoff, line 1, l1_then_l2) | no_kb_match | - | wrong_device_family | 2 | 41659 | 8.5 | - | - |
| INC-00028 | L2 | L2 (handoff, line 1, l2_now) | sop_trigger | runbooks/online-orders-aggregator-disconnect.md | verified | 2 | 41575 | 10.5 | third_party_integration_failure: The Zomato integration on our NetLink router has been offlin | - |
| INC-00043 | L2 | L1 (l1_pack, line 7, l1_guided) | - | runbooks/online-orders-sync-failure.md | verified | 2 | 41695 | 8.6 | - | - |
| INC-00069 | L2 | L1 (l1_pack, line 7, l1_guided) | - | runbooks/online-orders-sync-failure.md | verified | 2 | 40674 | 11.3 | - | - |
| INC-00017 | L1 | L1 (l1_pack, line 7, l1_guided) | - | runbooks/soft-serve-overcooling.md | verified | 2 | 40365 | 9.3 | - | - |
| INC-00021 | L1 | L1 (l1_pack, line 7, l1_guided) | - | runbooks/soft-serve-overcooling.md | verified | 2 | 40104 | 9.9 | - | - |
| INC-00053 | L2 | L2 (handoff, line 8, l2_now) | - | - | - | 2 | 41604 | 10.4 | - | - |
| INC-00074 | L1 | L1 (l1_pack, line 7, l1_guided) | - | runbooks/soft-serve-error-codes.md | verified | 2 | 42592 | 12.3 | - | - |
| INC-00078 | L2 | L2 (handoff, line 1, l2_now) | sop_trigger | runbooks/soft-serve-error-codes.md | verified | 2 | 42867 | 10.8 | error_not_in_kb: started showing the error around 3:45 PM during the afternoo | - |
| INC-00006 | L2 | L1 (l1_pack, line 7, l1_guided) | - | runbooks/network-guest-wifi.md | verified | 2 | 41615 | 10.4 | - | - |
| INC-00012 | L2 | L2 (handoff, line 1, l2_now) | sop_trigger | - | - | 2 | 42383 | 15.7 | customer_asks: We need this escalated for immediate investigation of potent | - |
| INC-00013 | L2 | L1 (l1_pack, line 7, l1_guided) | - | runbooks/network-slow.md | verified | 2 | 41472 | 10.4 | - | - |
| INC-00034 | L2 | L2 (l1_pack, line 7, l1_then_l2) | - | runbooks/network-slow.md | verified | 2 | 42304 | 12.7 | - | - |
| INC-00051 | L2 | L2 (l1_pack, line 7, l1_then_l2) | - | runbooks/network-vpn.md | verified | 2 | 42417 | 12.7 | - | - |

## `agent` (2026-11-19 04:13 UTC)

- K1 routing L1/L2: **87.5% (35/40)** (target >= 85%)
- K5 right runbook (L1-routed labelled tickets with a runbook): **100.0% (18/18)** (target >= 90%)
- Structured output valid: **100.0% (40/40)**; valid on the first try: 100.0% (40/40)
- Latency p50 9.9 s, max 13.8 s; tokens per ticket mean 42173, max 47019; LLM calls mean 3.0
- Rule X1: pass (K1 >= 85% and invalid output <= 5%)

| Ticket | Label | Agent | Handoff reason | Runbook | Quote check | Tools | Tokens | s | Model triggers | Conflicts |
|---|---|---|---|---|---|---|---|---|---|---|
| INC-00004 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/pos-pin-pad.md | verified | 2 | 42145 | 11.6 | - | - |
| INC-00008 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/pos-scanner.md | verified | 2 | 42256 | 11.1 | - | - |
| INC-00016 | L2 | L2 (resolver, line 6, l1_then_l2) | - | runbooks/printer-offline.md | verified | 2 | 43461 | 11.4 | - | - |
| INC-00031 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/printer-offline.md | verified | 2 | 41722 | 10.9 | - | - |
| INC-00041 | L2 | L2 (resolver, line 6, l1_then_l2) | - | runbooks/printer-driver-reinstall.md | verified | 2 | 43969 | 9.9 | - | - |
| INC-00060 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/pos-screen-frozen.md | verified | 2 | 42129 | 9.0 | - | - |
| INC-00064 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/printer-offline.md | verified | 2 | 42949 | 9.3 | - | - |
| INC-00068 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/printer-offline.md | verified | 2 | 42119 | 9.8 | - | - |
| INC-00090 | L2 | L2 (resolver, line 6, l1_then_l2) | - | runbooks/printer-offline.md | verified | 3 | 47019 | 10.8 | - | - |
| INC-00095 | L2 | L1 (resolver, line 6, l1_guided) | - | runbooks/pos-end-of-day.md | verified | 2 | 42772 | 13.0 | - | - |
| INC-00098 | L2 | L2 (resolver, line 6, l1_then_l2) | - | runbooks/pos-screen-frozen.md | verified | 2 | 43582 | 9.8 | - | - |
| INC-00102 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/printer-paper-jam.md | verified | 2 | 40561 | 9.9 | - | - |
| INC-00129 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/pos-screen-frozen.md | verified | 2 | 42010 | 9.1 | - | - |
| INC-00145 | L2 | L2 (resolver, line 6, l1_then_l2) | - | runbooks/pos-printer-integration.md | verified | 2 | 42897 | 10.0 | - | - |
| INC-00181 | L1 | L2 (handoff, line 1, l2_now) | conflict | runbooks/pos-end-of-day.md | verified | 2 | 41667 | 9.6 | - | runbooks/pos-end-of-day.md is explicitly limited to FoodTech POS v4.2.x and v5.1.x, while the ticket identifies OrbitPOS v2.0; its symptom match does not establish that this runbook applies to OrbitPOS. |
| INC-00183 | L2 | L2 (resolver, line 6, l1_then_l2) | - | runbooks/printer-offline.md | verified | 2 | 43911 | 8.9 | - | - |
| INC-00197 | L2 | L2 (resolver, line 6, l1_then_l2) | - | runbooks/printer-wrong-output.md | verified | 2 | 42323 | 9.9 | - | - |
| INC-00206 | L2 | L2 (resolver, line 6, l1_then_l2) | - | runbooks/printer-wrong-output.md | verified | 2 | 42802 | 9.0 | - | - |
| INC-00210 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/printer-wrong-output.md | verified | 2 | 41745 | 8.6 | - | - |
| INC-00216 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/pos-slow-performance.md | verified | 2 | 40878 | 9.5 | - | - |
| INC-00100 | L1 | L1 (l1_pack, line 7, l1_guided) | - | runbooks/kiosk-frozen.md | verified | 2 | 39771 | 12.5 | - | - |
| INC-00141 | L1 | L1 (l1_pack, line 7, l1_guided) | - | runbooks/kiosk-frozen.md | verified | 2 | 40393 | 13.1 | - | - |
| INC-00257 | L1 | L1 (l1_pack, line 7, l1_guided) | - | runbooks/kiosk-touchscreen.md | verified | 2 | 40239 | 9.9 | - | - |
| INC-00259 | L2 | L2 (handoff, line 1, l2_now) | sop_trigger | runbooks/kiosk-payment-reader.md | verified | 2 | 39680 | 13.1 | error_not_in_kb: displaying an error code E-402 whenever customers attempt to | - |
| INC-00262 | L1 | L1 (l1_pack, line 7, l1_guided) | - | runbooks/kiosk-software-crash.md | verified | 2 | 40405 | 9.1 | - | - |
| INC-00020 | L2 | L2 (handoff, line 1, l1_then_l2) | sop_trigger | runbooks/online-orders-not-on-kds.md | verified | 2 | 42585 | 11.3 | third_party_integration_failure: The issue persists across all three online delivery partner  | - |
| INC-00023 | L2 | L1 (l1_pack, line 7, l1_guided) | - | runbooks/online-orders-sync-failure.md | verified | 2 | 42177 | 10.9 | - | - |
| INC-00028 | L2 | L2 (handoff, line 1, l2_now) | sop_trigger | runbooks/online-orders-aggregator-disconnect.md | verified | 2 | 42198 | 10.4 | third_party_integration_failure: The Zomato integration on our NetLink router has been offlin | - |
| INC-00043 | L2 | L2 (l1_pack, line 7, l1_then_l2) | - | runbooks/online-orders-sync-failure.md | verified | 2 | 42235 | 9.8 | - | - |
| INC-00069 | L2 | L2 (l1_pack, line 7, l1_then_l2) | - | runbooks/online-orders-sync-failure.md | verified | 2 | 41184 | 10.0 | - | - |
| INC-00017 | L1 | L1 (l1_pack, line 7, l1_guided) | - | runbooks/soft-serve-overcooling.md | verified | 2 | 40952 | 9.6 | - | - |
| INC-00021 | L1 | L1 (l1_pack, line 7, l1_guided) | - | runbooks/soft-serve-overcooling.md | verified | 2 | 40576 | 9.9 | - | - |
| INC-00053 | L2 | L2 (handoff, line 8, l2_now) | - | - | - | 2 | 41993 | 8.6 | - | - |
| INC-00074 | L1 | L1 (l1_pack, line 7, l1_guided) | - | runbooks/soft-serve-error-codes.md | verified | 2 | 43235 | 13.8 | - | - |
| INC-00078 | L2 | L2 (handoff, line 1, l2_now) | sop_trigger | runbooks/soft-serve-error-codes.md | verified | 2 | 43289 | 11.5 | error_not_in_kb: displaying error code E-447; customer_asks: Staff are unable to process soft serve orders and customers  | - |
| INC-00006 | L2 | L1 (l1_pack, line 7, l1_guided) | - | runbooks/network-guest-wifi.md | verified | 2 | 42105 | 9.3 | - | - |
| INC-00012 | L2 | L2 (handoff, line 1, l2_now) | sop_trigger | runbooks/network-router-offline.md | verified | 2 | 42733 | 10.5 | network_failure: During these outages, all POS terminals lose network access,; customer_asks: We need this escalated for immediate investigation of potent | - |
| INC-00013 | L2 | L1 (l1_pack, line 7, l1_guided) | - | runbooks/network-slow.md | verified | 2 | 42036 | 9.0 | - | - |
| INC-00034 | L2 | L2 (handoff, line 1, l2_now) | sop_trigger | - | - | 2 | 43188 | 9.8 | network_failure: intermittent Wi-Fi connectivity drops on the NetLink NL-3000; customer_asks: We need immediate diagnostics and potential hardware replace | - |
| INC-00051 | L2 | L2 (handoff, line 1, l1_then_l2) | sop_trigger | runbooks/network-vpn.md | verified | 2 | 43012 | 9.6 | network_failure: The Cisco SG350-28GP managed switch (RTR-0074-01, firmware v | - |

## `agent` (2026-11-19 04:15 UTC)

- K1 routing L1/L2: **90.0% (36/40)** (target >= 85%)
- K5 right runbook (L1-routed labelled tickets with a runbook): **100.0% (18/18)** (target >= 90%)
- Structured output valid: **100.0% (40/40)**; valid on the first try: 100.0% (40/40)
- Latency p50 9.7 s, max 14.4 s; tokens per ticket mean 42360, max 65313; LLM calls mean 3.0
- Rule X1: pass (K1 >= 85% and invalid output <= 5%)

| Ticket | Label | Agent | Handoff reason | Runbook | Quote check | Tools | Tokens | s | Model triggers | Conflicts |
|---|---|---|---|---|---|---|---|---|---|---|
| INC-00004 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/pos-pin-pad.md | verified | 2 | 42124 | 9.5 | - | - |
| INC-00008 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/pos-scanner.md | verified | 2 | 42077 | 9.8 | - | - |
| INC-00016 | L2 | L2 (resolver, line 6, l1_then_l2) | - | runbooks/printer-offline.md | verified | 2 | 43633 | 9.6 | - | - |
| INC-00031 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/printer-offline.md | verified | 2 | 41906 | 9.7 | - | - |
| INC-00041 | L2 | L2 (resolver, line 6, l1_then_l2) | - | runbooks/printer-driver-reinstall.md | verified | 2 | 44313 | 9.2 | - | - |
| INC-00060 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/pos-screen-frozen.md | verified | 2 | 42223 | 8.5 | - | - |
| INC-00064 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/printer-offline.md | verified | 2 | 43097 | 8.9 | - | - |
| INC-00068 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/printer-offline.md | verified | 2 | 42296 | 8.4 | - | - |
| INC-00090 | L2 | L2 (resolver, line 6, l1_then_l2) | - | runbooks/pos-printer-integration.md | verified | 2 | 42409 | 10.2 | - | - |
| INC-00095 | L2 | L2 (resolver, line 6, l1_then_l2) | - | runbooks/pos-end-of-day.md | verified | 2 | 43592 | 14.4 | - | - |
| INC-00098 | L2 | L2 (resolver, line 6, l1_then_l2) | - | runbooks/pos-screen-frozen.md | verified | 2 | 43429 | 9.9 | - | - |
| INC-00102 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/printer-paper-jam.md | verified | 2 | 40548 | 9.4 | - | - |
| INC-00129 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/pos-screen-frozen.md | verified | 2 | 42375 | 9.0 | - | - |
| INC-00145 | L2 | L2 (resolver, line 6, l1_then_l2) | - | runbooks/printer-wrong-output.md | verified | 2 | 42892 | 11.5 | - | - |
| INC-00181 | L1 | L2 (resolver, line 6, l1_then_l2) | - | runbooks/pos-end-of-day.md | verified | 2 | 42275 | 11.2 | - | - |
| INC-00183 | L2 | L2 (resolver, line 6, l1_then_l2) | - | runbooks/pos-printer-integration.md | verified | 2 | 43791 | 10.9 | - | - |
| INC-00197 | L2 | L2 (resolver, line 6, l1_then_l2) | - | runbooks/printer-wrong-output.md | verified | 2 | 42687 | 12.6 | - | - |
| INC-00206 | L2 | L2 (resolver, line 6, l1_then_l2) | - | runbooks/printer-wrong-output.md | verified | 2 | 43109 | 11.0 | - | - |
| INC-00210 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/printer-wrong-output.md | verified | 2 | 41982 | 9.8 | - | - |
| INC-00216 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/pos-slow-performance.md | verified | 2 | 40963 | 8.4 | - | - |
| INC-00100 | L1 | L1 (l1_pack, line 7, l1_guided) | - | runbooks/kiosk-frozen.md | verified | 2 | 40041 | 10.0 | - | - |
| INC-00141 | L1 | L1 (l1_pack, line 7, l1_guided) | - | runbooks/kiosk-frozen.md | verified | 2 | 40198 | 8.8 | - | - |
| INC-00257 | L1 | L1 (l1_pack, line 7, l1_guided) | - | runbooks/kiosk-touchscreen.md | verified | 2 | 40430 | 9.0 | - | - |
| INC-00259 | L2 | L2 (handoff, line 1, l2_now) | sop_trigger | runbooks/kiosk-payment-reader.md | verified | 2 | 40023 | 11.0 | error_not_in_kb: displaying an error code E-402 whenever customers attempt to | - |
| INC-00262 | L1 | L2 (l1_pack, line 7, l1_then_l2) | - | runbooks/kiosk-software-crash.md | verified | 2 | 40760 | 9.8 | - | - |
| INC-00020 | L2 | L2 (handoff, line 1, l1_then_l2) | sop_trigger | runbooks/online-orders-not-on-kds.md | verified | 2 | 42658 | 10.0 | third_party_integration_failure: The issue persists across all three online delivery partner  | - |
| INC-00023 | L2 | L2 (handoff, line 1, l1_guided) | no_kb_match | - | wrong_device_family | 2 | 42368 | 9.7 | - | - |
| INC-00028 | L2 | L2 (handoff, line 1, l2_now) | sop_trigger | runbooks/online-orders-aggregator-disconnect.md | verified | 2 | 42342 | 9.9 | third_party_integration_failure: The Zomato integration on our NetLink router has been offlin | - |
| INC-00043 | L2 | L2 (handoff, line 8, l2_now) | - | - | - | 2 | 42670 | 12.6 | - | - |
| INC-00069 | L2 | L2 (handoff, line 1, l1_then_l2) | no_kb_match | - | - | 1 | 24410 | 6.9 | - | - |
| INC-00017 | L1 | L1 (l1_pack, line 7, l1_guided) | - | runbooks/soft-serve-overcooling.md | verified | 2 | 41196 | 10.9 | - | - |
| INC-00021 | L1 | L1 (l1_pack, line 7, l1_guided) | - | runbooks/soft-serve-overcooling.md | verified | 2 | 40771 | 8.9 | - | - |
| INC-00053 | L2 | L2 (handoff, line 8, l2_now) | - | - | - | 2 | 42279 | 9.5 | - | - |
| INC-00074 | L1 | L1 (l1_pack, line 7, l1_guided) | - | runbooks/soft-serve-error-codes.md | verified | 2 | 43033 | 9.1 | - | - |
| INC-00078 | L2 | L2 (handoff, line 1, l2_now) | sop_trigger | runbooks/soft-serve-error-codes.md | verified | 2 | 43653 | 13.9 | error_not_in_kb: started showing the error around 3:45 PM during the afternoo | - |
| INC-00006 | L2 | L1 (l1_pack, line 7, l1_guided) | - | runbooks/network-guest-wifi.md | verified | 2 | 42350 | 8.9 | - | - |
| INC-00012 | L2 | L2 (handoff, line 1, l2_now) | sop_trigger | runbooks/network-slow.md | verified | 3 | 65313 | 12.1 | customer_asks: We need this escalated for immediate investigation of potent; network_failure: During these outages, all POS terminals lose network access, | - |
| INC-00013 | L2 | L1 (l1_pack, line 7, l1_guided) | - | runbooks/network-slow.md | verified | 2 | 42173 | 9.2 | - | - |
| INC-00034 | L2 | L2 (l1_pack, line 7, l1_then_l2) | - | runbooks/network-slow.md | verified | 2 | 42978 | 10.9 | - | - |
| INC-00051 | L2 | L2 (handoff, line 1, l1_then_l2) | sop_trigger | runbooks/network-vpn.md | verified | 2 | 43020 | 9.5 | network_failure: The VPN drops approximately every 15–20 minutes for 2–3 minu | - |

## `agent` (2026-11-19 04:17 UTC)

- K1 routing L1/L2: **95.0% (38/40)** (target >= 85%)
- K5 right runbook (L1-routed labelled tickets with a runbook): **100.0% (18/18)** (target >= 90%)
- Structured output valid: **100.0% (40/40)**; valid on the first try: 100.0% (40/40)
- Latency p50 9.8 s, max 12.7 s; tokens per ticket mean 43217, max 65163; LLM calls mean 3.0
- Rule X1: pass (K1 >= 85% and invalid output <= 5%)

| Ticket | Label | Agent | Handoff reason | Runbook | Quote check | Tools | Tokens | s | Model triggers | Conflicts |
|---|---|---|---|---|---|---|---|---|---|---|
| INC-00004 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/pos-pin-pad.md | verified | 2 | 42184 | 9.7 | - | - |
| INC-00008 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/pos-scanner.md | verified | 2 | 42353 | 12.1 | - | - |
| INC-00016 | L2 | L2 (resolver, line 6, l1_then_l2) | - | runbooks/printer-offline.md | verified | 2 | 43570 | 12.1 | - | - |
| INC-00031 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/printer-offline.md | verified | 2 | 41839 | 8.8 | - | - |
| INC-00041 | L2 | L2 (resolver, line 6, l1_then_l2) | - | runbooks/printer-driver-reinstall.md | verified | 2 | 44084 | 10.9 | - | - |
| INC-00060 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/pos-screen-frozen.md | verified | 2 | 42241 | 10.1 | - | - |
| INC-00064 | L1 | L2 (resolver, line 6, l1_then_l2) | - | runbooks/printer-offline.md | verified | 2 | 43156 | 11.4 | - | - |
| INC-00068 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/printer-offline.md | verified | 2 | 42295 | 9.9 | - | - |
| INC-00090 | L2 | L2 (resolver, line 6, l1_then_l2) | - | runbooks/pos-printer-integration.md | verified | 2 | 42394 | 9.4 | - | - |
| INC-00095 | L2 | L2 (resolver, line 6, l1_then_l2) | - | runbooks/pos-end-of-day.md | verified | 2 | 43165 | 10.4 | - | - |
| INC-00098 | L2 | L2 (resolver, line 6, l1_then_l2) | - | runbooks/pos-screen-frozen.md | verified | 2 | 43655 | 11.3 | - | - |
| INC-00102 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/printer-paper-jam.md | verified | 2 | 40655 | 9.2 | - | - |
| INC-00129 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/pos-screen-frozen.md | verified | 2 | 42511 | 8.6 | - | - |
| INC-00145 | L2 | L2 (resolver, line 6, l1_then_l2) | - | runbooks/printer-wrong-output.md | verified | 2 | 42758 | 10.1 | - | - |
| INC-00181 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/pos-end-of-day.md | verified | 2 | 42052 | 9.4 | - | - |
| INC-00183 | L2 | L2 (handoff, line 1, l2_now) | sop_trigger | runbooks/printer-offline.md | verified | 2 | 44478 | 11.4 | error_not_in_kb: error code E-PRINT-502 ('Printer communication timeout') | - |
| INC-00197 | L2 | L2 (resolver, line 6, l1_then_l2) | - | runbooks/printer-wrong-output.md | verified | 2 | 42436 | 9.7 | - | - |
| INC-00206 | L2 | L2 (resolver, line 6, l1_then_l2) | - | runbooks/printer-wrong-output.md | verified | 2 | 43072 | 10.8 | - | - |
| INC-00210 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/printer-wrong-output.md | verified | 2 | 42119 | 10.6 | - | - |
| INC-00216 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/pos-slow-performance.md | verified | 2 | 40903 | 8.3 | - | - |
| INC-00100 | L1 | L1 (l1_pack, line 7, l1_guided) | - | runbooks/kiosk-frozen.md | verified | 2 | 39925 | 8.8 | - | - |
| INC-00141 | L1 | L1 (l1_pack, line 7, l1_guided) | - | runbooks/kiosk-frozen.md | verified | 2 | 40195 | 9.0 | - | - |
| INC-00257 | L1 | L1 (l1_pack, line 7, l1_guided) | - | runbooks/kiosk-touchscreen.md | verified | 2 | 40351 | 9.3 | - | - |
| INC-00259 | L2 | L2 (handoff, line 1, l2_now) | sop_trigger | runbooks/kiosk-payment-reader.md | verified | 2 | 39894 | 11.5 | error_not_in_kb: displaying an error code E-402 | - |
| INC-00262 | L1 | L1 (l1_pack, line 7, l1_guided) | - | runbooks/kiosk-software-crash.md | verified | 2 | 40546 | 8.8 | - | - |
| INC-00020 | L2 | L2 (handoff, line 1, l1_then_l2) | sop_trigger | runbooks/online-orders-not-on-kds.md | verified | 2 | 42736 | 9.4 | third_party_integration_failure: The issue persists across all three online delivery partner  | - |
| INC-00023 | L2 | L2 (handoff, line 1, l1_guided) | no_kb_match | - | wrong_device_family | 2 | 42726 | 12.7 | - | - |
| INC-00028 | L2 | L2 (handoff, line 1, l2_now) | sop_trigger | runbooks/online-orders-aggregator-disconnect.md | verified | 2 | 42467 | 8.7 | third_party_integration_failure: The Zomato integration on our NetLink router has been offlin | - |
| INC-00043 | L2 | L2 (l1_pack, line 7, l1_then_l2) | - | runbooks/online-orders-sync-failure.md | verified | 3 | 61688 | 12.3 | - | - |
| INC-00069 | L2 | L2 (l1_pack, line 7, l1_then_l2) | - | runbooks/online-orders-sync-failure.md | verified | 2 | 41363 | 9.5 | - | - |
| INC-00017 | L1 | L1 (l1_pack, line 7, l1_guided) | - | runbooks/soft-serve-overcooling.md | verified | 2 | 41078 | 9.4 | - | - |
| INC-00021 | L1 | L1 (l1_pack, line 7, l1_guided) | - | runbooks/soft-serve-overcooling.md | verified | 2 | 40990 | 12.3 | - | - |
| INC-00053 | L2 | L1 (l1_pack, line 7, l1_guided) | - | runbooks/soft-serve-motor-alarm.md | verified | 2 | 40367 | 10.3 | - | - |
| INC-00074 | L1 | L1 (l1_pack, line 7, l1_guided) | - | runbooks/soft-serve-error-codes.md | verified | 2 | 43225 | 10.9 | - | - |
| INC-00078 | L2 | L2 (handoff, line 1, l2_now) | sop_trigger | runbooks/soft-serve-error-codes.md | verified | 2 | 43452 | 8.9 | error_not_in_kb: started showing the error around 3:45 PM during the afternoo | - |
| INC-00006 | L2 | L2 (l1_pack, line 7, l1_then_l2) | - | runbooks/network-guest-wifi.md | verified | 2 | 42361 | 9.6 | - | - |
| INC-00012 | L2 | L2 (handoff, line 1, l2_now) | sop_trigger | runbooks/network-slow.md | verified | 3 | 65163 | 11.9 | network_failure: all POS terminals lose network access, preventing order proc; customer_asks: We need this escalated for immediate investigation of potent | - |
| INC-00013 | L2 | L2 (handoff, line 1, l2_now) | sop_trigger | runbooks/network-slow.md | verified | 2 | 42190 | 9.7 | network_failure: Multiple customer and staff devices unable to obtain IP addr | - |
| INC-00034 | L2 | L2 (l1_pack, line 7, l1_then_l2) | - | runbooks/network-slow.md | verified | 2 | 42815 | 8.7 | - | - |
| INC-00051 | L2 | L2 (l1_pack, line 7, l1_then_l2) | - | runbooks/network-vpn.md | verified | 2 | 43223 | 11.8 | - | - |

## `agent` (2026-11-19 06:04 UTC)

- K1 routing L1/L2: **97.5% (39/40)** (target >= 85%)
- K5 right runbook (L1-routed labelled tickets with a runbook): **100.0% (18/18)** (target >= 90%)
- Structured output valid: **100.0% (40/40)**; valid on the first try: 100.0% (40/40)
- Latency p50 10.2 s, max 15.2 s; tokens per ticket mean 43955, max 64429; LLM calls mean 3.0
- Rule X1: pass (K1 >= 85% and invalid output <= 5%)

| Ticket | Label | Agent | Handoff reason | Runbook | Quote check | Tools | Tokens | s | Model triggers | Conflicts |
|---|---|---|---|---|---|---|---|---|---|---|
| INC-00004 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/pos-pin-pad.md | verified | 2 | 42945 | 10.3 | - | - |
| INC-00008 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/pos-scanner.md | verified | 2 | 43030 | 10.1 | - | - |
| INC-00016 | L2 | L2 (resolver, line 6, l1_then_l2) | - | runbooks/printer-offline.md | verified | 2 | 44445 | 11.3 | - | - |
| INC-00031 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/printer-offline.md | verified | 2 | 42693 | 11.2 | - | - |
| INC-00041 | L2 | L1 (resolver, line 6, l1_guided) | - | runbooks/printer-driver-reinstall.md | verified | 2 | 44883 | 9.7 | - | - |
| INC-00060 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/pos-screen-frozen.md | verified | 2 | 43206 | 14.1 | - | - |
| INC-00064 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/printer-offline.md | verified | 2 | 44034 | 9.6 | - | - |
| INC-00068 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/printer-offline.md | verified | 2 | 43089 | 9.9 | - | - |
| INC-00090 | L2 | L2 (resolver, line 6, l1_then_l2) | - | runbooks/printer-offline.md | verified | 2 | 43640 | 10.1 | - | - |
| INC-00095 | L2 | L2 (resolver, line 6, l1_then_l2) | - | runbooks/pos-end-of-day.md | verified | 2 | 43795 | 13.1 | - | - |
| INC-00098 | L2 | L2 (resolver, line 6, l1_then_l2) | - | runbooks/pos-screen-frozen.md | verified | 2 | 44251 | 9.7 | - | - |
| INC-00102 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/printer-paper-jam.md | verified | 2 | 41439 | 9.3 | - | - |
| INC-00129 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/pos-screen-frozen.md | verified | 2 | 43003 | 9.7 | - | - |
| INC-00145 | L2 | L2 (handoff, line 1, l1_then_l2) | sop_trigger | runbooks/printer-wrong-output.md | verified | 2 | 43558 | 9.2 | customer_asks: Advised escalation to L2 hardware support for potential prin | - |
| INC-00181 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/pos-end-of-day.md | verified | 2 | 42814 | 10.3 | - | - |
| INC-00183 | L2 | L2 (resolver, line 6, l1_then_l2) | - | runbooks/printer-offline.md | verified | 2 | 44888 | 9.8 | - | - |
| INC-00197 | L2 | L2 (resolver, line 6, l1_then_l2) | - | runbooks/printer-wrong-output.md | verified | 2 | 43305 | 9.8 | - | - |
| INC-00206 | L2 | L2 (resolver, line 6, l1_then_l2) | - | runbooks/printer-wrong-output.md | verified | 2 | 44002 | 11.5 | - | - |
| INC-00210 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/printer-wrong-output.md | verified | 2 | 42718 | 9.8 | - | - |
| INC-00216 | L1 | L1 (resolver, line 6, l1_guided) | - | runbooks/pos-slow-performance.md | verified | 2 | 41689 | 9.3 | - | - |
| INC-00100 | L1 | L1 (l1_pack, line 7, l1_guided) | - | runbooks/kiosk-frozen.md | verified | 2 | 40713 | 10.2 | - | - |
| INC-00141 | L1 | L1 (l1_pack, line 7, l1_guided) | - | runbooks/kiosk-frozen.md | verified | 2 | 41210 | 10.7 | - | - |
| INC-00257 | L1 | L1 (l1_pack, line 7, l1_guided) | - | runbooks/kiosk-touchscreen.md | verified | 2 | 41222 | 9.3 | - | - |
| INC-00259 | L2 | L2 (handoff, line 1, l2_now) | sop_trigger | runbooks/kiosk-payment-reader.md | verified | 2 | 40523 | 10.6 | error_not_in_kb: displaying an error code E-402 whenever customers attempt to | - |
| INC-00262 | L1 | L1 (l1_pack, line 7, l1_guided) | - | runbooks/kiosk-software-crash.md | verified | 2 | 41542 | 10.3 | - | - |
| INC-00020 | L2 | L2 (handoff, line 1, l1_then_l2) | sop_trigger | runbooks/online-orders-not-on-kds.md | verified | 2 | 43507 | 11.3 | third_party_integration_failure: The issue persists across all three online delivery partner  | - |
| INC-00023 | L2 | L2 (handoff, line 1, l1_guided) | no_kb_match | - | wrong_device_family | 2 | 43164 | 9.8 | - | - |
| INC-00028 | L2 | L2 (handoff, line 1, l2_now) | sop_trigger | runbooks/online-orders-aggregator-disconnect.md | verified | 2 | 43174 | 10.6 | third_party_integration_failure: The Zomato integration on our NetLink router has been offlin | - |
| INC-00043 | L2 | L2 (l1_pack, line 7, l1_then_l2) | - | runbooks/online-orders-sync-failure.md | verified | 2 | 43160 | 10.3 | - | - |
| INC-00069 | L2 | L2 (l1_pack, line 7, l1_then_l2) | - | runbooks/online-orders-sync-failure.md | verified | 2 | 42157 | 10.1 | - | - |
| INC-00017 | L1 | L1 (l1_pack, line 7, l1_guided) | - | runbooks/soft-serve-overcooling.md | verified | 2 | 41917 | 10.0 | - | - |
| INC-00021 | L1 | L1 (l1_pack, line 7, l1_guided) | - | runbooks/soft-serve-overcooling.md | verified | 2 | 58205 | 14.1 | - | - |
| INC-00053 | L2 | L2 (handoff, line 8, l2_now) | - | - | - | 2 | 43160 | 12.3 | - | - |
| INC-00074 | L1 | L1 (l1_pack, line 7, l1_guided) | - | runbooks/soft-serve-error-codes.md | verified | 2 | 43845 | 10.5 | - | - |
| INC-00078 | L2 | L2 (handoff, line 1, l2_now) | sop_trigger | runbooks/soft-serve-error-codes.md | verified | 2 | 44298 | 9.2 | error_not_in_kb: started showing the error around 3:45 PM during the afternoo | - |
| INC-00006 | L2 | L2 (l1_pack, line 7, l1_then_l2) | - | runbooks/network-guest-wifi.md | verified | 2 | 43042 | 9.8 | - | - |
| INC-00012 | L2 | L2 (handoff, line 1, l2_now) | sop_trigger | runbooks/network-router-offline.md | verified | 2 | 43845 | 10.2 | network_failure: all POS terminals lose network access, preventing order proc; customer_asks: We need this escalated for immediate investigation of potent | - |
| INC-00013 | L2 | L2 (l1_pack, line 7, l1_then_l2) | - | runbooks/network-slow.md | verified | 3 | 64429 | 15.2 | - | - |
| INC-00034 | L2 | L2 (handoff, line 1, l1_then_l2) | sop_trigger | runbooks/network-slow.md | verified | 2 | 43800 | 9.8 | network_failure: intermittent Wi-Fi connectivity drops on the NetLink NL-3000 | - |
| INC-00051 | L2 | L2 (handoff, line 1, l1_then_l2) | sop_trigger | runbooks/network-vpn.md | verified | 2 | 43857 | 11.5 | network_failure: The Cisco SG350-28GP managed switch (RTR-0074-01, firmware v; third_party_integration_failure: during disconnections, orders cannot be synced to the centra | - |

