# k9_tune: INC-00059 (K9)

Subject: Receipt printer offline — contradicts earlier resolution ticket INC-00015
Category: Printers

Agent messages to the store, in order:
- [framing_template] Hi, for ticket SWT-B3FB8391B543, please do the next step below and reply with what you see (for example the lights, the screen message or whether it prints).
- [step] 2. **Printer Self-Test**
   - Press and hold the **FEED button** on the printer for 3–5 seconds to initiate self-test
   - Verify paper loads and prints test pattern (confirms hardware is functional)
   - If self-test prints successfully, issue is driver or connectivity related
- [status_template] Hi, your ticket SWT-B3FB8391B543 is now with our L2 support team (priority P2). They will contact you by 21:25 IST on 06 Dec.
Store replies, in order:
- I held the FEED button for 3–5 seconds, but the printer still doesn’t print.
IT actions run:
- none
Walk: runbook runbooks/printer-offline.md, steps po-self-test (store: replied)
Ticket ended: status escalated, route resolver, handoff reason version_not_covered

## l2_note

Ticket ID: SWT-B3FB8391B543
Executive summary: Receipt printer for POS terminal POS-0066-T1 (asset type: POS Terminal; real device: Receipt Printer) is offline and not responding to print jobs. Routed to L2 for the version coverage gap: the consulted runbook (runbooks/printer-offline.md) does not cover OrbitPOS v2.1; the escalation reason is version_not_covered. Priority is P2 after the +1 peak-hours rule; the asset is out of warranty, so repair is paid.
Store: SW-0066 ServeWell - Chromepet, Chromepet, Chennai (franchise)
Asset ID: unavailable: linked POS-0066-T1 is a POS Terminal, not the Receipt Printer (asset not verified)
Asset type: Receipt Printer
Store contact: on file (vault)
Error code or message: offline
First occurrence: reported 2025-12-06T15:25+00:00
Frequency: Persistent since this morning; it worked yesterday afternoon after the reported fix.
Steps tried and outcome: 1) USB cable connections checked by store staff -> Connections appear intact.; 2) Printer power checked -> Printer powers on.; 3) Print jobs sent from the POS terminal -> Printer does not respond.; 4) Held the FEED button for 3–5 seconds for a self-test -> Printer still does not print.
KB resources consulted: runbooks/printer-offline.md
Devices affected: One receipt printer, connected to terminal POS-0066-T1.
Users affected: Customers are not receiving receipts; staff report the issue. Counts unavailable.
Business impact: Customers are not receiving receipts; the printer is completely non-functional again.
Workaround: unavailable: no workaround is reported
Priority and overrides: P2 (+1 peak hours)
Escalation reason: version_not_covered
Version coverage gap: runbooks/printer-offline.md does not cover OrbitPOS v2.1.
Escalated at: 2025-12-06T15:27+00:00

Trick type: contradictory. Pass when the agent handled the trick as its type expects (agent-check.md E-cases).
