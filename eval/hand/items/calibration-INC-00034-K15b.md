# calibration: INC-00034 (K15b)

Subject: NetLink NL-3000 router experiencing frequent intermittent connectivity drops affecting POS and ordering terminals
Category: Wi-Fi / Network

Agent messages to the store, in order:
- [status_template] Hi, your ticket SWT-64851BDA6531 is now with our L2 support team (priority P3). They will contact you by 16:12 IST on 03 Nov.
Store replies, in order:
- none
IT actions run:
- none
Walk: runbook runbooks/network-slow.md, steps 
Ticket ended: status escalated, route l1_pack, handoff reason gate_block

## l2_note

Ticket ID: SWT-64851BDA6531
Executive summary: NetLink NL-3000 v2.1 network router (asset RTR-0092-01; registered asset, type Network Router) has intermittent Wi-Fi drops affecting both bands, recurring every 15–25 minutes and disrupting POS, online ordering synchronization, and staff kitchen-display devices. L2 Network handling is requested because the drops persist despite initial checks, cause significant business impact, and the store requests hardware replacement evaluation; priority is P3, the asset is in warranty, and no specific SOP trigger is listed.
Store: SW-0092 ServeWell - Kandivali, Kandivali, Mumbai (corporate)
Asset ID: RTR-0092-01
Asset type: Network Router (NetLink NL-3000 NetLink NL-3000, NetLink NL-3000 v2.1)
Store contact: on file (vault)
Error code or message: No error lights are visible on the device front panel
First occurrence: reported 2025-11-03T09:42+00:00
Frequency: Intermittent; drops approximately every 15–25 minutes, lasting 2–5 minutes per instance, since 2025-11-02 at approximately 19:30 IST.
Steps tried and outcome: 1) Power-cycled the router twice with 5-minute intervals. -> Issue persists; no successful resolution reported.; 2) Verified WAN and LAN cable connections are secure. -> Connections confirmed secure.; 3) Checked for loose antenna connections. -> No loose connections reported.; 4) Reviewed connected device count. -> Stable at 18 devices.; 5) Confirmed whether recent configuration changes were made. -> No recent configuration changes.; 6) Checked router uptime before the issue began. -> Uptime was 8 days without issues prior to yesterday evening.; 7) Checked connectivity across Wi-Fi bands and router status. -> Drops affect both 2.4 GHz and 5 GHz; router maintains IP address 192.168.1.1 throughout the drops.; 8) L1 initial validation; advised the store to check for firmware updates and monitor logs. -> Advice given; completion or result not known.; 9) Sent remote diagnostics request to capture router syslog for the last 24 hours and monitor DHCP lease renewals during the next drop window. -> Request sent; results not known.; 10) Consulted runbooks/network-slow.md. -> Runbook symptom evidence: “Intermittent disconnections with automatic reconnection”.
KB resources consulted: runbooks/network-slow.md
Devices affected: NetLink NL-3000 router; drops affect both 2.4 GHz and 5 GHz Wi-Fi. POS terminals, online ordering terminals/synchronization, and staff mobile devices used for kitchen displays are affected.
Users affected: Staff using the affected devices; number of users not known. Customer impact is reported as frustration during peak lunch hours.
Business impact: Significant: each drop causes transaction delays and customer frustration during peak lunch hours (12:00–14:00).
Workaround: No workaround reported.
Priority and overrides: P3 (+1 corporate location; -1 known issue with workaround)
Escalation reason: gate_block
Warranty: in warranty (62 days left): vendor route
Version coverage gap: none: the runbook covers this version
Escalated at: 2025-11-03T09:42+00:00

## Expected (label)

- Routing: l2_escalation; escalation reason: Intermittent network connectivity issue on critical infrastructure (NetLink NL-3000 router) affecting multiple business-critical systems (POS, online ordering, KDS). Extensive L1 troubleshooting already performed with no resolution. Business impact is significant during peak hours. Hardware diagnostics and potential replacement evaluation required, which exceeds L1 scope.
- Resolution: Escalate to L2 Network team with collected diagnostics (syslog, DHCP lease renewal patterns, packet capture during drop windows). L2 should perform remote packet analysis, firmware version verification against known issues, and evaluate hardware health metrics. If diagnostics indicate hardware failure, initiate replacement of RTR-0092-01 with expedited shipping to critical location.
- Tricky-ticket behaviour: PASS: Agent confirms escalation to L2 Network team is appropriate, ensures all diagnostic data (syslog, device logs, DHCP monitoring results) is compiled in the escalation ticket, and communicates timeline expectations to store manager. FAIL: Agent attempts generic troubleshooting already completed, fails to escalate despite P3 priority and business impact, or does not request additional diagnostics before escalation.

## Judge's reason (score blind first, then compare)

The note accurately describes intermittent drops on the NetLink NL-3000 affecting POS, online ordering, and kitchen-display devices, with significant peak-hour impact and multiple L1 checks already performed without resolution. It requests L2 handling and hardware replacement evaluation, and the syslog/DHCP diagnostics align with the expected next step. However, the escalation field says “gate_block,” which does not match the expected reason, and the note does not explicitly call for packet capt
