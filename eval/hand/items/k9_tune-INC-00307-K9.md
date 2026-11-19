# k9_tune: INC-00307 (K9)

Subject: PIN pad not responding at register
Category: POS

Agent messages to the store, in order:
- [status_template] Hi, your ticket SWT-BDAC4ADB6BF1 is now with our L2 support team (priority P1). They will contact you by 19:51 IST on 27 Dec.
Store replies, in order:
- none
IT actions run:
- none
Walk: runbook runbooks/pos-pin-pad.md, steps 
Ticket ended: status escalated, route resolver, handoff reason no_approved_steps

## l2_note

Ticket ID: SWT-BDAC4ADB6BF1
Executive summary: The PIN pad had a blank screen and could not process card payments, while the register continued to work. The issue is being handed to L2 because the runbook walk found no approved steps; the history reports that a power cycle resolved the issue and card transactions are working normally.
Store: SW-0051 ServeWell - Miyapur, Miyapur, Hyderabad (corporate)
Asset ID: unavailable: linked POS-0051-T1 is a POS Terminal, not the PIN Pad (asset not verified)
Asset type: PIN Pad
Store contact: on file (vault)
Error code or message: unavailable: no error code or message was reported; the store described a blank screen.
First occurrence: reported 2025-12-27T14:06+00:00
Frequency: persistent until the power cycle, based on the terminal being completely down and then responding normally after the power cycle.
Steps tried and outcome: 1) Store reported the PIN pad had stopped working after working earlier that morning; nothing was showing on the screen. -> PIN pad completely down; customers could not make card payments.; 2) L1 advised power cycling the PIN pad. -> Store confirmed this resolved the issue; PIN pad responds and processes card transactions normally.; 3) L1 advised checking physical connections. -> unavailable: no result for the connection check was recorded.; 4) Runbook walk for runbooks/pos-pin-pad.md. -> Walk ended with runbook_has_no_approved_steps.
KB resources consulted: runbooks/pos-pin-pad.md
Devices affected: One PIN pad; linked asset POS-0051-T1 is a POS Terminal, so the PIN pad asset is not verified.
Users affected: Customers were unable to make card payments. Number of customers and staff affected: unavailable.
Business impact: Store reported losing business because customers could not pay by card; issue is now reported resolved.
Workaround: Power cycling the PIN pad resolved the issue.
Priority and overrides: P1 (+1 peak hours; +1 corporate location)
Escalation reason: no_approved_steps
Version coverage gap: unavailable: runbook version coverage is null; coverage for FoodTech POS v5.1.0 is not known.
Escalated at: 2025-12-27T14:06+00:00

Trick type: vague. Pass when the agent handled the trick as its type expects (agent-check.md E-cases).
