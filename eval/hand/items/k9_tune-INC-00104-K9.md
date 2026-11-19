# k9_tune: INC-00104 (K9)

Subject: WiFi completely broken AGAIN - DHCP issue, can't take this anymore
Category: Wi-Fi / Network

Agent messages to the store, in order:
- [status_template] Hi, your ticket SWT-B7D5C4A61C5D is now with our L2 support team (priority P2). They will contact you by 13:37 IST on 06 Nov.
Store replies, in order:
- none
IT actions run:
- none
Walk: runbook runbooks/network-guest-wifi.md, steps 
Ticket ended: status escalated, route handoff, handoff reason sop_trigger

## l2_note

Ticket ID: SWT-B7D5C4A61C5D
Executive summary: Network Router NetLink NL-3000 v2.2 (asset RTR-0023-01) at Saket has intermittent Wi-Fi drops all morning; the store says this is the third network problem this month. L2 handoff is warranted because staff and guest connectivity are affected outside the guest-only L1 paths, repeated reboots have not helped, and the store explicitly asks for a fix today (SOP trigger: customer_asks). Priority is P2 (peak-hours +1 and customer-escalation P1/P2 + manager rules); the asset is in warranty, so use the vendor route. Consulted runbooks/network-guest-wifi.md and runbooks/network-router-offline.md; no document conflict or version coverage gap is established.
Store: SW-0023 ServeWell - Saket, Saket, Delhi (franchise)
Asset ID: RTR-0023-01
Asset type: Network Router (NetLink NL-3000 NetLink NL-3000, NetLink NL-3000 v2.2)
Store contact: on file (vault)
Error code or message: unavailable: no error code or message was reported; “DHCP” is mentioned but not reported as an error
First occurrence: reported 2025-11-06T07:37+00:00
Frequency: Intermittent; drops occurred all morning, and the store reports this is the third network problem this month.
Steps tried and outcome: 1) Rebooted the router about ten times. -> No difference.; 2) Attempted phone contact. -> Customer did not answer.; 3) Sent diagnostic instructions by email to check DHCP pool status and report the current connected-device count. -> unavailable: no response or result recorded
KB resources consulted: runbooks/network-guest-wifi.md, runbooks/network-router-offline.md
Devices affected: Wi-Fi-connected devices; the store specifically reports staff tablets cannot load orders. The total device count is not known.
Users affected: Guests and staff.
Business impact: Store reports difficulty processing payments properly, lost customers, and a frustrated team.
Workaround: unavailable: no workaround reported
Priority and overrides: P2 (+1 peak hours; customer escalation P1/P2 + manager)
Escalation reason: sop_trigger: Intermittent Wi-Fi affecting both guests and staff does not clearly fit the guest-only scope of this runbook, but its symptom matches; repeated router reboots are already tried, and staff-network impact falls outside its guest-only L1 paths. The store explicitly asks for someone to fix it today, though the evidence does not establish total payment failure or a confirmed router-wide outage.
SOP trigger and evidence: customer_asks ("I need someone to fix this TODAY because I can't keep making excuses to customers.")
Warranty: in warranty (206 days left): vendor route
Version coverage gap: none established; the runbook's version coverage is not specified.
Escalated at: 2025-11-06T07:37+00:00

Trick type: emotional. Pass when the agent handled the trick as its type expects (agent-check.md E-cases).
