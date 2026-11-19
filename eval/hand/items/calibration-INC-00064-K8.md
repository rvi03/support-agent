# calibration: INC-00064 (K8)

Subject: Receipt printer not printing orders at POS terminal T1
Category: Printers

Agent messages to the store, in order:
- [framing_template] Hi, for ticket SWT-1055B6ABAE72, please do the next step below and reply with what you see (for example the lights, the screen message or whether it prints).
- [step] 1. **Physical Check**
   - Verify the printer is powered on (check LED indicator)
   - For USB printers: confirm cable is firmly connected to both printer and POS terminal
   - For network printers: confirm ethernet cable is firmly connected and switch/router is powered on
- [framing_template] Hi, for ticket SWT-1055B6ABAE72, please do the next step below and reply with what you see (for example the lights, the screen message or whether it prints).
- [step] 2. **Printer Self-Test**
   - Press and hold the **FEED button** on the printer for 3–5 seconds to initiate self-test
   - Verify paper loads and prints test pattern (confirms hardware is functional)
   - If self-test prints successfully, issue is driver or connectivity related
- [framing_template] Hi, for ticket SWT-1055B6ABAE72, please do the next step below and reply with what you see (for example the lights, the screen message or whether it prints).
- [step] 3. **Restart POS Application**
   - Close ServeWell POS completely
   - Wait 10 seconds
   - Reopen ServeWell POS and check if printer status updates to "Online"
- [status_template] Hi, your ticket SWT-1055B6ABAE72 is now with our L2 support team (priority P2). They will contact you by 21:28 IST on 22 Dec.
Store replies, in order:
- The printer is powered on, but POS test receipts still don’t print and jobs remain in the queue.
- I ran the printer self-test as requested; it printed successfully, but POS test receipts still don’t print and remain queued.
- I restarted ServeWell POS as instructed, but POS test receipts still don’t print and pending jobs remain in the queue.
IT actions run:
- none
Walk: runbook runbooks/printer-offline.md, steps po-physical-check (store: replied), po-self-test (store: replied), po-restart-pos-app (store: replied)
Ticket ended: status escalated, route resolver, handoff reason version_not_covered

## l2_note

Ticket ID: SWT-1055B6ABAE72
Executive summary: The receipt printer connected to POS terminal T1 persistently fails to print customer receipts; the linked asset POS-0052-T1 is a POS Terminal, so the printer asset is not verified. Orders are processing normally, but the store cannot provide order confirmations. Handoff reason: version_not_covered—the printer model/version is unavailable, and no further generic steps are approved; priority is P2 (P3 raised by +1 for peak hours). The linked POS terminal is out of warranty; the printer's warranty is not known.
Store: SW-0052 ServeWell - Adyar, Adyar, Chennai (franchise)
Asset ID: unavailable: linked POS-0052-T1 is a POS Terminal, not the Receipt Printer (asset not verified)
Asset type: Receipt Printer
Store contact: on file (vault)
Error code or message: The system shows no response when attempting to print test receipts.
First occurrence: reported 2025-12-22T15:28+00:00
Frequency: Persistent since approximately 20:45 today.
Steps tried and outcome: 1) Restart POS terminal (advised in ticket history). -> Not known; no result recorded.; 2) Check USB/network cable connections to printer (advised in ticket history). -> Not known; no result recorded.; 3) Physical check. -> Store reported the printer is powered on; POS test receipts still do not print and jobs remain queued.; 4) Run printer self-test. -> Self-test printed successfully; POS test receipts still do not print and remain queued.; 5) Restart POS app (reported by store as ServeWell POS). -> POS test receipts still do not print and pending jobs remain queued.
KB resources consulted: runbooks/printer-offline.md
Devices affected: One receipt printer connected to POS terminal T1; printer asset not verified. Linked asset POS-0052-T1 is a POS Terminal.
Users affected: Not known.
Business impact: Orders are processing normally, but customer service cannot provide order confirmations.
Workaround: Not known.
Priority and overrides: P2 (+1 peak hours)
Escalation reason: version_not_covered
Version coverage gap: Runbook runbooks/printer-offline.md consulted. Printer model/version is not provided, so coverage cannot be confirmed; only generic steps may be used, and no further generic steps are approved. FoodTech POS v4.2.2 is reported as the system version.
Escalated at: 2025-12-22T15:35+00:00

## Expected (label)

- Routing: l1_guided; escalation reason: -
- Resolution: Agent should guide through POS printer integration troubleshooting: verify printer power and connectivity, check print queue status in FoodTech POS v4.2.2, restart the POS terminal and printer, verify USB/network cable connections, reinstall or update printer drivers if needed, and perform test print. If issue persists after these steps, escalate to L2.
- Tricky-ticket behaviour: PASS: Agent retrieves pos-printer-integration.md runbook and guides user through systematic troubleshooting (power check, connection verification, queue clearing, restart sequence, driver verification). FAIL: Agent escalates immediately without attempting L1 troubleshooting, provides generic advice without referencing runbooks, or misses checking basic connectivity/power status.

## Judge's reason (score blind first, then compare)

The agent checked printer power and connections, ran a successful printer self-test, and restarted the POS application before escalating after the issue persisted. However, it used the generic printer-offline runbook rather than pos-printer-integration.md and missed key L1 steps: checking or clearing the FoodTech POS v4.2.2 queue, restarting the POS terminal and printer, and verifying or updating drivers. The escalation therefore came before the expected troubleshooting sequence was complete.
