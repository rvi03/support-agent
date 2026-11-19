# k9_tune: INC-00198 (K9)

Subject: Printer not detected - why does nothing ever work around here
Category: Printers

Agent messages to the store, in order:
- [status_template] Hi, your ticket SWT-586FD264877C is now with our L2 support team (priority P2). They will contact you by 11:35 IST on 27 Dec.
Store replies, in order:
- none
IT actions run:
- none
Walk: runbook runbooks/printer-offline.md, steps 
Ticket ended: status escalated, route handoff, handoff reason sop_trigger

## l2_note

Ticket ID: SWT-586FD264877C
Executive summary: Receipt Printer EpsonTM-T88VI (asset PRN-0035-P1) is reported as “Printer not detected” and stopped working again; the store says this is the third occurrence this month, bills are not printing, and payments are affected. Handoff is under SOP trigger customer_asks, with the store requesting “Make it work or send someone here to actually help.” Priority is P2 per policy, with peak-hours and customer-escalation overrides; the asset is in warranty, so the vendor route applies.
Store: SW-0035 ServeWell - Madhapur, Madhapur, Hyderabad (franchise)
Asset ID: PRN-0035-P1
Asset type: Receipt Printer (EpsonTM-T88VI EpsonTM-T88VI, EpsonTM-T88VI v1.12)
Store contact: on file (vault)
Error code or message: Printer not detected
First occurrence: reported 2025-12-27T05:35+00:00
Frequency: intermittent
Steps tried and outcome: 1) Troubleshooting steps in ticket history and description -> None recorded.; 2) Consulted runbooks/printer-offline.md -> The symptoms section covers a printer not appearing in Windows Devices and Printers; no troubleshooting step or result is recorded.
KB resources consulted: runbooks/printer-offline.md
Devices affected: Receipt Printer PRN-0035-P1; additional affected devices not known.
Users affected: 20 customers are reported in the queue; number of affected store staff is not known.
Business impact: Store reports bills are not printing and payments cannot be processed properly; customers are waiting and angry.
Workaround: unavailable: no workaround is stated in the ticket data.
Priority and overrides: P2 (+1 peak hours; customer escalation P1/P2 + manager)
Escalation reason: sop_trigger: The linked Epson receipt printer and “Printer not detected” symptom fit printer-offline, but no troubleshooting steps are recorded; the stated third occurrence this month and frustration do not prove basic checks were already run. The store explicitly requests someone to help, so customer_asks applies; L1 should guide through the runbook and then escalate if needed.
SOP trigger and evidence: customer_asks ("Make it work or send someone here to actually help.")
Warranty: in warranty (25 days left): vendor route
Version coverage gap: unavailable: runbook version coverage is not stated
Escalated at: 2025-12-27T05:35+00:00

Trick type: emotional. Pass when the agent handled the trick as its type expects (agent-check.md E-cases).
