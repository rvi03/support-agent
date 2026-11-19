# calibration: INC-00227 (K8)

Subject: Epson Receipt Printer PRN-0056-P1 Not Detected on Network
Category: Printers

Agent messages to the store, in order:
- [framing_template] Hi, for ticket SWT-FAAAF9823C4A, please do the next step below and reply with what you see (for example the lights, the screen message or whether it prints).
- [step] 1. **Physical Check**
   - Verify the printer is powered on (check LED indicator)
   - For USB printers: confirm cable is firmly connected to both printer and POS terminal
   - For network printers: confirm ethernet cable is firmly connected and switch/router is powered on
- [framing_template] Hi, for ticket SWT-FAAAF9823C4A, please do the next step below and reply with what you see (for example the lights, the screen message or whether it prints).
- [step] 2. **Printer Self-Test**
   - Press and hold the **FEED button** on the printer for 3–5 seconds to initiate self-test
   - Verify paper loads and prints test pattern (confirms hardware is functional)
   - If self-test prints successfully, issue is driver or connectivity related
- [framing_template] Hi, for ticket SWT-FAAAF9823C4A, please do the next step below and reply with what you see (for example the lights, the screen message or whether it prints).
- [step] 3. **Restart POS Application**
   - Close ServeWell POS completely
   - Wait 10 seconds
   - Reopen ServeWell POS and check if printer status updates to "Online"
- [framing_template] Hi, for ticket SWT-FAAAF9823C4A, please do the next step below and reply with what you see (for example the lights, the screen message or whether it prints).
- [step] 1. On the printer itself, press and hold the **FEED button** and **POWER button** simultaneously for 5 seconds to print network configuration page
2. Locate the **IP Address** line on the printout
- [status_template] Hi, your ticket SWT-FAAAF9823C4A is now with our L2 support team (priority P4). They will contact you by 09:01 IST on 14 Feb.
Store replies, in order:
- I checked the power and connections; the POS still doesn’t detect the printer.
- I ran the printer self-test, but the POS still doesn’t detect it.
- I restarted ServeWell POS as instructed, but the printer is still not detected.
- I held FEED and POWER for 5 seconds, but the POS still doesn’t detect the printer.
IT actions run:
- none
Walk: runbook runbooks/printer-offline.md, steps po-physical-check (store: replied), po-self-test (store: replied), po-restart-pos-app (store: replied), po-net-config-page (store: replied)
Ticket ended: status escalated, route resolver, handoff reason steps_exhausted

## l2_note

Ticket ID: SWT-FAAAF9823C4A
Executive summary: Receipt Printer: Epson Receipt Printer PRN-0056-P1 Not Detected on Network. Handed to L2 with reason steps_exhausted; this note was built by code from the ticket.
Store: SW-0056 ServeWell - Kadugodi, Kadugodi, Bengaluru (franchise)
Asset ID: PRN-0056-P1
Asset type: Receipt Printer (EpsonTM-T88VI EpsonTM-T88VI, EpsonTM-T88VI v1.12)
Store contact: on file (vault)
Error code or message: unavailable: see the store's description under Business impact
First occurrence: reported 2026-02-14T01:31+00:00
Frequency: unavailable: not stated in a form code can read
Steps tried and outcome: 1) tried before (ticket): po-net-power-cycle; 2) walk turn 1: po-physical-check (store) -> replied: I checked the power and connections; the POS still doesn’t detect the printer.; 3) walk turn 2: po-self-test (store) -> replied: I ran the printer self-test, but the POS still doesn’t detect it.; 4) walk turn 3: po-restart-pos-app (store) -> replied: I restarted ServeWell POS as instructed, but the printer is still not detected.; 5) walk turn 4: po-net-config-page (store) -> replied: I held FEED and POWER for 5 seconds, but the POS still doesn’t detect the printer.; 6) walk ended: The network configuration page step was already attempted, but the reply does not provide the printer's IP address or say whether the page printed. The next approved network step requires that IP addr
KB resources consulted: runbooks/printer-offline.md
Devices affected: unavailable: not stated in a form code can read
Users affected: unavailable: not stated in a form code can read
Business impact: as reported by the store: "The Epson TM-T88VI receipt printer at the Kadugodi store is not being detected by the POS system. The printer was operational yesterday but failed to initialize this morning during opening. The device appears to be powered on (LED indicator visible), but no communication is established with the main counter workstation. We attempted a basic power cycle but the issue persists. This printer is critical for order receipts during peak hours."
Workaround: unavailable: none recorded
Priority and overrides: P4 (no overrides)
Escalation reason: steps_exhausted
Warranty: in warranty (542 days left): vendor route
Version coverage gap: none: the runbook covers this version
Escalated at: 2026-02-14T01:40+00:00

## Expected (label)

- Routing: l1_guided; escalation reason: -
- Resolution: Agent should guide through network connectivity diagnostics including verifying network connection status on the workstation, checking IP address assignment/DHCP, verifying printer network settings via control panel, checking firewall rules, and testing printer connectivity with ping/nslookup commands. If network connectivity is confirmed but printer still not detected, reinstall or update printer drivers. If issue persists after these steps, escalate to L2.
- Tricky-ticket behaviour: PASS: Agent retrieves pos-printer-integration.md and/or printer-offline.md and guides through systematic troubleshooting starting with network connectivity checks, printer configuration, and driver verification before escalation. FAIL: Agent immediately escalates without attempting guided troubleshooting, or suggests solutions unrelated to network connectivity (e.g., only recommends power cycle which was already attempted).

## Judge's reason (score blind first, then compare)

The agent used the printer-offline runbook and did not escalate immediately; the physical check and network-configuration-page step are partly relevant, and escalation is an appropriate eventual outcome. However, it escalated without guiding the store through the expected network diagnostics: workstation connection status, DHCP/IP verification, printer settings review, firewall checks, ping/nslookup, or driver verification. The store still reported that the printer was not detected.
