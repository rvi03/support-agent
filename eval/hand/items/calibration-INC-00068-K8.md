# calibration: INC-00068 (K8)

Subject: Receipt printer offline at Bhandup store
Category: Printers

Agent messages to the store, in order:
- [framing_template] Hi, for ticket SWT-3A07EFAC5CB5, please do the next step below and reply with what you see (for example the lights, the screen message or whether it prints).
- [step] 1. **Physical Check**
   - Verify the printer is powered on (check LED indicator)
   - For USB printers: confirm cable is firmly connected to both printer and POS terminal
   - For network printers: confirm ethernet cable is firmly connected and switch/router is powered on
- [framing_template] Hi, for ticket SWT-3A07EFAC5CB5, please do the next step below and reply with what you see (for example the lights, the screen message or whether it prints).
- [step] 2. **Printer Self-Test**
   - Press and hold the **FEED button** on the printer for 3–5 seconds to initiate self-test
   - Verify paper loads and prints test pattern (confirms hardware is functional)
   - If self-test prints successfully, issue is driver or connectivity related
- [framing_template] Hi, for ticket SWT-3A07EFAC5CB5, please do the next step below and reply with what you see (for example the lights, the screen message or whether it prints).
- [step] 3. **Restart POS Application**
   - Close ServeWell POS completely
   - Wait 10 seconds
   - Reopen ServeWell POS and check if printer status updates to "Online"
- [status_template] Hi, your ticket SWT-3A07EFAC5CB5 is now with our L2 support team (priority P2). They will contact you by 19:56 IST on 12 May.
Store replies, in order:
- The power light is on, but the POS still doesn’t print receipts and Windows doesn’t list the Epson printer.
- I tried the FEED-button self-test, but receipts still aren’t printing.
- I restarted ServeWell POS as instructed, but the printer is still not listed in Windows and no receipts print.
IT actions run:
- none
Walk: runbook runbooks/printer-offline.md, steps po-physical-check (store: replied), po-self-test (store: replied), po-restart-pos-app (store: replied)
Ticket ended: status escalated, route resolver, handoff reason steps_exhausted

## l2_note

Ticket ID: SWT-3A07EFAC5CB5
Executive summary: The verified receipt printer (EpsonTM-T88VI v1.12) at the counter is not printing, and Windows does not list it. L2 handoff is needed because the immediate checks are complete, but the remaining diagnosis depends on whether it is USB- or network-connected, which is not known.
Store: SW-0019 ServeWell - Bhandup, Bhandup, Mumbai (corporate)
Asset ID: PRN-0019-P2
Asset type: Receipt Printer (EpsonTM-T88VI EpsonTM-T88VI, EpsonTM-T88VI v1.12)
Store contact: on file (vault)
Error code or message: No error messages visible on the device.
First occurrence: reported 2026-05-12T13:56+00:00
Frequency: unavailable: occurrence and frequency are not stated
Steps tried and outcome: 1) Checked the printer’s physical status. -> The power light is on, but the POS still doesn’t print receipts and Windows doesn’t list the Epson printer.; 2) Tried the FEED-button self-test. -> Receipts still aren’t printing.; 3) Restarted ServeWell POS as instructed. -> The printer is still not listed in Windows and no receipts print.; 4) Determine the connection type for the remaining connection-specific diagnosis. -> Unable to select the remaining diagnosis steps because whether the printer is USB- or network-connected is not identified.
KB resources consulted: runbooks/printer-offline.md
Devices affected: One receipt printer.
Users affected: unavailable: number of affected users is not stated
Business impact: The counter cannot print receipts; further business impact is not stated.
Workaround: unavailable: no workaround is stated
Priority and overrides: P2 (+1 peak hours; +1 corporate location)
Escalation reason: steps_exhausted
Warranty: in warranty (506 days left): vendor route
Version coverage gap: none: the runbook covers this version
Escalated at: 2026-05-12T14:02+00:00

## Expected (label)

- Routing: l1_guided; escalation reason: -
- Resolution: Agent should retrieve the printer-offline runbook to guide troubleshooting steps for the Epson TM-T88VI receipt printer. Initial steps should include verifying power supply, checking physical connections, restarting the printer, and confirming network/USB connectivity. If basic troubleshooting fails, escalate to L2 for hardware diagnostics or replacement.
- Tricky-ticket behaviour: PASS: Agent retrieves printer-offline.md and epson-printer.md specs, provides structured troubleshooting steps appropriate for a receipt printer offline issue. FAIL: Agent escalates prematurely without attempting guided troubleshooting, misses the available runbooks, or provides generic advice without referencing device specifications.

## Judge's reason (score blind first, then compare)

The agent retrieved and followed the printer-offline runbook, checking power and connections, running a FEED-button self-test, and restarting the POS before escalating after the store still reported failure. Escalation to L2 is appropriate after these steps, but the expected behaviour also calls for retrieving epson-printer.md and checking device-specific guidance, plus restarting the printer; neither is shown.
