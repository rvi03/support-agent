# calibration: INC-00314 (K15b)

Subject: RTR-0037-01 entering continuous crash loop – unable to accept customer orders
Category: Kiosks

Agent messages to the store, in order:
- [status_template] Hi, your ticket SWT-9B9A6DB47CF2 is now with our L2 support team (priority P1). They will contact you by 21:14 IST on 11 May.
Store replies, in order:
- none
IT actions run:
- none
Walk: runbook runbooks/kiosk-software-crash.md, steps 
Ticket ended: status escalated, route handoff, handoff reason sop_trigger

## l2_note

Ticket ID: SWT-9B9A6DB47CF2
Executive summary: Self-Order Kiosk: RTR-0037-01 entering continuous crash loop – unable to accept customer orders. Handed to L2 with reason sop_trigger; this note was built by code from the ticket.
Store: SW-0037 ServeWell - Nagarbhavi, Nagarbhavi, Bengaluru (corporate)
Asset ID: unavailable: linked RTR-0037-01 is a Network Router, not the Self-Order Kiosk (asset not verified)
Asset type: Self-Order Kiosk
Store contact: on file (vault)
Error code or message: unavailable: see the store's description under Business impact
First occurrence: reported 2026-05-11T15:29+00:00
Frequency: unavailable: not stated in a form code can read
Steps tried and outcome: 1) history: Ticket triaged and reviewed. Confirmed customer has performed standard power cycle and cable checks. Assigned to Level 2 Kiosk Support for remote diagnostics and potential firmware rollback assessment.; 2) history: Attempted remote connection to RTR-0037-01 management interface but unit does not respond due to crash loop preventing network stability. Escalation to onsite technician recommended given P2 priority and business impact during peak hours.
KB resources consulted: runbooks/kiosk-software-crash.md
Devices affected: unavailable: not stated in a form code can read
Users affected: unavailable: not stated in a form code can read
Business impact: as reported by the store: "The NetLink NL-3000 v2.2 kiosk (RTR-0037-01) at Nagarbhavi location has been experiencing a critical software crash loop since approximately 20:45 IST today. The unit boots and displays the ServeWell menu splash screen for 8–12 seconds, then abruptly black-screens and automatically restarts. This cycle repeats continuously without allowing customer interaction or order placement. No error codes or diagnostic messages are visible during the crash. We have already attempted the following troubleshooting steps: (1) performed a hard power cycle by disconnecting and reconnecting the unit for 30 sec"
Workaround: unavailable: none recorded
Priority and overrides: P1 (+1 peak hours; +1 corporate location; customer escalation P1/P2 + manager)
Escalation reason: sop_trigger: The splash-to-black restart loop and inability to place orders match the kiosk crash-loop runbook. The linked asset is a router and no kiosk is listed for this store; hard power cycle and cable checks were already done, so L1 should pass to L2 for kiosk diagnostics.
SOP trigger and evidence: customer_asks ("Request immediate technical intervention to diagnose root cause and restore functionality.")
Version coverage gap: unavailable: not assessed (code-built note)
Escalated at: 2026-05-11T15:29+00:00

## Expected (label)

- Routing: l2_escalation; escalation reason: P2 priority hardware/software issue with continuous crash loop preventing order processing during peak business hours. L1 troubleshooting (power cycle, cable checks, network verification) completed without resolution. Unit unresponsive to remote diagnostics. Requires onsite technician intervention and potential firmware rollback or hardware replacement.
- Resolution: Escalate to L2 Kiosk Support with onsite technician dispatch to diagnose root cause of continuous crash loop in NetLink NL-3000 v2.2 unit (RTR-0037-01). Perform firmware rollback, apply pending updates, or replace hardware if defective. Restore kiosk functionality to resume digital order processing during peak hours.
- Tricky-ticket behaviour: Pass: Agent correctly identifies this as a P2 critical issue requiring L2 escalation and onsite technician support. Agent references kiosk-software-crash.md runbook, confirms all L1 troubleshooting steps have been exhausted, documents business impact, and initiates escalation with clear context. Fail: Agent attempts to resolve via remote diagnostics only, does not escalate despite P2 priority and failed remote connection attempts, or fails to document business impact of peak-hour downtime.

## Judge's reason (score blind first, then compare)

The note captures the continuous crash loop, inability to accept orders, completed power-cycle and cable checks, and failed remote access. Its history recommends an onsite technician, but the stated escalation rationale mainly says to pass the case to L2 and does not clearly call for dispatch or firmware rollback/hardware replacement as the expected resolution does. It also labels priority P1 rather than the expected P2 and flags the linked asset as a router, though it explicitly says the kiosk 
