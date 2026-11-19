# calibration: INC-00223 (K15b)

Subject: POS Terminal T1 Cash Drawer Not Responding to Open/Close Commands
Category: POS

Agent messages to the store, in order:
- [status_template] Hi, your ticket SWT-88DF26A3ADA6 is now with our L2 support team (priority P3). They will contact you by 10:33 IST on 27 Mar.
Store replies, in order:
- none
IT actions run:
- none
Walk: runbook runbooks/pos-cash-drawer.md, steps 
Ticket ended: status escalated, route handoff, handoff reason sop_trigger

## l2_note

Ticket ID: SWT-88DF26A3ADA6
Executive summary: POS Terminal POS-0064-T1 (FoodTech POS v4.2.1) had a persistent cash-drawer timeout and no physical response. It was escalated under the error-not-in-KB trigger because code 0x2847 is not listed in the runbook; SOP priority was P3, reduced for a known issue with a workaround. Later ticket history records a solenoid replacement and successful post-repair testing, with the terminal fully operational.
Store: SW-0064 ServeWell - Kompally, Kompally, Hyderabad (franchise)
Asset ID: POS-0064-T1
Asset type: POS Terminal (FoodTech POS FoodTech POS Terminal 1, FoodTech POS v4.2.1)
Store contact: on file (vault)
Error code or message: Cash Drawer Error: Device Timeout (Code 0x2847)
First occurrence: reported 2026-03-27T04:03+00:00
Frequency: Persistent since approximately 08:45 AM today; drawer worked normally yesterday evening.
Steps tried and outcome: 1) Staff power-cycled the terminal twice. -> Issue persisted.; 2) Staff restarted the POS application. -> Issue persisted.; 3) L1 restarted the terminal and rebooted the POS. -> Device timeout persisted.; 4) L1 checked the USB cable connection to the cash drawer. -> Cable was secure.; 5) L1 checked for a FoodTech POS v4.2.1 firmware update. -> No update was available.; 6) Consulted runbooks/pos-cash-drawer.md. -> The manual drawer-open symptom matched the runbook; error code 0x2847 was not listed.; 7) Hardware technician replaced the cash-drawer solenoid assembly. -> Drawer opened and closed correctly; code 0x2847 stopped appearing. Customer confirmed normal function during post-repair testing; T1 was fully operational.
KB resources consulted: runbooks/pos-cash-drawer.md
Devices affected: Cash drawer on POS Terminal T1 (asset POS-0064-T1); one of two terminals was affected. Backup drawer on T2 handled overflow.
Users affected: Store staff and customers; number of users not known.
Business impact: Degraded mode during peak lunch service; staff manually recorded cash received, causing queue delays. Full POS restoration was described as urgent.
Workaround: Staff manually recorded cash received; backup drawer on T2 handled overflow.
Priority and overrides: P3 (-1 known issue with workaround)
Escalation reason: sop_trigger: The cash-drawer symptom matches the POS cash-drawer runbook, but L1 already checked the secure cable, restarted the terminal/POS, and verified the issue persisted; the reported code 0x2847 is not listed in the runbook. Hardware repair documented in later ticket history is not used to determine triage.
SOP trigger and evidence: error_not_in_kb ("Error message displayed on POS screen: 'Cash Drawer Error: Device Timeout (Code 0x2847)'")
Warranty: in warranty (264 days left): vendor route
Version coverage gap: none: the runbook covers this version
Escalated at: 2026-03-27T04:03+00:00

## Expected (label)

- Routing: l2_escalation; escalation reason: Hardware failure (solenoid actuator malfunction) requires on-site technician intervention; L1 troubleshooting (restart, cable verification, firmware check) did not resolve the issue and confirmed device timeout persists, necessitating L2 hardware diagnostics and replacement.
- Resolution: The cash drawer solenoid actuator assembly on POS terminal T1 had failed, preventing mechanical response to control signals and generating error code 0x2847. An on-site hardware technician replaced the faulty solenoid assembly, restoring full cash drawer functionality and POS operability by 11:50 AM.
- Tricky-ticket behaviour: PASS: Agent correctly identifies persistent hardware failure after L1 troubleshooting steps (restart, cable check, firmware verification) and escalates to L2 for on-site hardware diagnostics and repair. FAIL: Agent attempts further software troubleshooting, suggests customer performs additional restarts, or delays escalation despite clear hardware error code persistence.

## Judge's reason (score blind first, then compare)

The note accurately records the persistent timeout, L1 restart/cable/firmware checks, and business impact during peak lunch service, and it documents that solenoid replacement restored operation. However, it gives the escalation reason as an error-not-in-KB trigger and says the later hardware repair is not used for triage, rather than identifying suspected solenoid failure and the need for on-site hardware diagnostics/replacement. It also omits the expected restoration time of 11:50 AM.
