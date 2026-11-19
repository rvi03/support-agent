# calibration: INC-00120 (K15b)

Subject: Payment processing timeout on Terminal 1 - multiple failed card transactions
Category: POS

Agent messages to the store, in order:
- [status_template] Hi, your ticket SWT-D5A7845C7EC7 is now with our L2 support team (priority P4). They will contact you by 19:47 IST on 25 Dec.
Store replies, in order:
- none
IT actions run:
- none
Walk: runbook runbooks/pos-payment-error.md, steps 
Ticket ended: status escalated, route handoff, handoff reason sop_trigger

## l2_note

Ticket ID: SWT-D5A7845C7EC7
Executive summary: FoodTech POS Terminal 1 (POS-0018-T1) has persistent card payment timeouts, while cash payments work and Terminal 2 is processing payments normally. Intermittent customer charges and duplicate transactions create a financial-integrity concern, so the ticket is with L2 for payment gateway and processor diagnostics.
Store: SW-0018 ServeWell - Viman Nagar, Viman Nagar, Pune (franchise)
Asset ID: POS-0018-T1
Asset type: POS Terminal (FoodTech POS FoodTech POS Terminal 1, FoodTech POS v4.2.3)
Store contact: on file (vault)
Error code or message: ERR-4521 ("Payment Gateway Timeout")
First occurrence: reported 2025-12-25T12:17+00:00
Frequency: persistent
Steps tried and outcome: 1) Restarted the terminal twice. -> Card payment failures continued.; 2) Checked Ethernet and WiFi connectivity. -> Both showed normal signal strength; L1 later confirmed the terminal was online and network connectivity stable.; 3) Verified internet speed. -> 45 Mbps download / 12 Mbps upload.; 4) Reviewed POS logs. -> Found repeated gateway timeout entries.; 5) Initiated remote access to terminal logs. -> Initiated; no further outcome stated.; 6) Verified payment gateway connection parameters. -> Parameters were correct.; 7) Checked for local POS configuration issues. -> No local POS configuration issues detected.; 8) Checked payment processor status and gateway server logs. -> Awaiting L2; no result stated.
KB resources consulted: runbooks/pos-payment-error.md
Devices affected: One device: Terminal 1 (POS-0018-T1). Terminal 2 is processing payments without incident.
Users affected: Customers attempting credit/debit card transactions; number not known.
Business impact: Peak dinner rush service is delayed; 8 transactions were manually voided and reprocessed in the last 15 minutes, causing customer dissatisfaction and delays. Some cards are charged intermittently, creating duplicate charges.
Workaround: Cash transactions on Terminal 1 process normally. The store manually voided and reprocessed 8 transactions; further outcome not stated.
Priority and overrides: P4 (-1 known issue with workaround)
Escalation reason: sop_trigger: The payment failures are isolated to one terminal while Terminal 2 still works, but intermittent charges and duplicate transactions create a data-loss/financial integrity concern. L1 also documented gateway checks and routed it to the L2 Payment Systems team; ERR-4521 is not listed in the runbook, though it describes a payment gateway timeout.
SOP trigger and evidence: payment_failure ("Terminal 1 (POS-0018-T1) has been experiencing consistent payment processing failures during card transactions."); data_loss ("customer cards are being charged intermittently, creating duplicate charges in some cases.")
Warranty: in warranty (108 days left): vendor route
Version coverage gap: unavailable: runbook version coverage is not stated; triage notes ERR-4521 is not listed in the runbook
Escalated at: 2025-12-25T12:17+00:00

## Expected (label)

- Routing: l2_escalation; escalation reason: Payment gateway timeout errors (ERR-4521) with duplicate charges require L2 Payment Systems team investigation of gateway server logs, processor status, and gateway connection parameters. Terminal-level troubleshooting has been exhausted; issue is likely on payment processor backend or gateway infrastructure.
- Resolution: L2 Payment Systems should: (1) review payment processor gateway server logs for connection failures or rate-limiting during the 17:30 IST timeframe, (2) verify gateway API endpoint health and response times, (3) check for any ongoing incidents with the payment processor, (4) coordinate with payment processor to investigate duplicate charge occurrences and initiate refunds if necessary, (5) perform test transactions on Terminal 1 to confirm resolution before returning to production.
- Tricky-ticket behaviour: PASS: Agent acknowledges ticket is appropriately escalated to L2, confirms all L1 troubleshooting steps were thorough and documented, provides L2 team with clear context (error code ERR-4521, timeframe, symptom of duplicate charges, network/terminal diagnostics already ruled out). FAIL: Agent attempts additional terminal-level fixes, doesn't escalate, suggests customer-side payment method issues, or provides generic advice without L2 handoff.

## Judge's reason (score blind first, then compare)

The note identifies ERR-4521 gateway timeouts and intermittent duplicate charges as the escalation concern, and routes the issue to L2 for payment gateway and processor diagnostics, consistent with the expected reason and resolution. It documents extensive terminal/network troubleshooting and the dinner-rush delays and eight manually voided/reprocessed transactions. It does not specify several expected L2 actions, such as checking API endpoint health, investigating processor incidents, handling 
