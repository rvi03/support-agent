# calibration: INC-00096 (K15b)

Subject: Soft serve machine not powering on at Paschim Vihar
Category: Soft Serve

Agent messages to the store, in order:
- [status_template] Hi, your ticket SWT-9319FE95C9AB is now with our L2 support team (priority P3). They will contact you by 12:38 IST on 28 Dec.
Store replies, in order:
- none
IT actions run:
- none
Walk: runbook None, steps 
Ticket ended: status escalated, route handoff, handoff reason l2_needed

## l2_note

Ticket ID: SWT-9319FE95C9AB
Executive summary: Soft Serve Machine: Soft serve machine not powering on at Paschim Vihar. Handed to L2 with reason l2_needed; this note was built by code from the ticket.
Store: SW-0110 ServeWell - Paschim Vihar, Paschim Vihar, Delhi (franchise)
Asset ID: unavailable: linked RTR-0110-01 is a Network Router, not the Soft Serve Machine (asset not verified)
Asset type: Soft Serve Machine
Store contact: on file (vault)
Error code or message: unavailable: see the store's description under Business impact
First occurrence: reported 2025-12-28T06:08+00:00
Frequency: unavailable: not stated in a form code can read
Steps tried and outcome: unavailable: no steps in the ticket history
KB resources consulted: runbooks/soft-serve-error-codes.md
Devices affected: unavailable: not stated in a form code can read
Users affected: unavailable: not stated in a form code can read
Business impact: as reported by the store: "The soft serve machine (RTR-0110-01) won't start. No response when switched on. Need urgent check as lunch rush starting soon."
Workaround: unavailable: none recorded
Priority and overrides: P3 (+1 peak hours)
Escalation reason: l2_needed
Version coverage gap: unavailable: not assessed (code-built note)
Escalated at: 2025-12-28T06:08+00:00

## Expected (label)

- Routing: l2_escalation; escalation reason: Machine complete failure (no power response) requires immediate hardware diagnostic or on-site technician intervention. L1 troubleshooting cannot resolve a non-responsive device, and business impact is high due to lunch rush timing.
- Resolution: Verify power supply connection and circuit breaker status. If no response after basic power checks, escalate to L2 field technician for hardware diagnostic and potential replacement. Confirm machine asset RTR-0110-01 configuration and review recent maintenance logs.
- Tricky-ticket behaviour: PASS: Agent retrieves soft-serve runbooks, attempts basic power/connection troubleshooting steps, recognizes machine unresponsiveness indicates hardware failure, escalates to L2 with full context (asset ID, store location, time sensitivity). FAIL: Agent attempts only software troubleshooting, delays escalation, fails to acknowledge urgency of lunch rush impact, or provides incomplete escalation information.

## Judge's reason (score blind first, then compare)

The note captures the no-response failure and lunch-rush urgency, and accurately states that no troubleshooting steps are recorded. It flags that RTR-0110-01 is linked as a network router rather than treating it as a verified soft-serve asset. However, “l2_needed” does not explain the expected immediate hardware-diagnostic escalation, and the note gives no next steps for checking power and the breaker, reviewing maintenance logs, or arranging field technician intervention.
