# k9_tune: INC-00054 (K9)

Subject: POS Terminal T1 Not Responding - Connection Lost
Category: Wi-Fi / Network

Agent messages to the store, in order:
- [status_template] Hi, your ticket SWT-C1F9CC6478B0 is now with our L2 support team (priority P2). They will contact you by 15:37 IST on 28 Mar.
Store replies, in order:
- none
IT actions run:
- none
Walk: runbook runbooks/network-router-offline.md, steps 
Ticket ended: status escalated, route handoff, handoff reason sop_trigger

## l2_note

Ticket ID: SWT-C1F9CC6478B0
Executive summary: POS terminal T1 (linked asset POS-0053-T1, POS Terminal) stopped responding during peak lunch service with a store-wide network outage; the real device implicated is the Network Router, and its asset is not verified. Escalated to L2 now under P2 for the network_failure SOP trigger, supported by the reported evidence: “the router light indicator is off and there is no connectivity to other networked devices in the store either”; the router-offline runbook was consulted (runbooks/network-router-offline.md). The linked POS asset is out of warranty; if repair is required, the route is paid repair.
Store: SW-0053 ServeWell - Rajajinagar, Rajajinagar, Bengaluru (franchise)
Asset ID: unavailable: linked POS-0053-T1 is a POS Terminal, not the Network Router (asset not verified)
Asset type: Network Router
Store contact: on file (vault)
Error code or message: Unable to connect to server
First occurrence: reported 2026-03-28T09:37+00:00
Frequency: Persistent; first occurrence approximately 15:00 IST, with the issue persisting after two restarts.
Steps tried and outcome: 1) Restarted the POS terminal twice (reported in the description). -> Issue persists.; 2) L1 requested that the store manager verify router status and check power connections. -> Store reported the router indicator is off and other networked devices have no connectivity; power-connection check result not known.; 3) Store investigation found the WiFi network was not broadcasting and staff devices could not connect to the internet. -> Connectivity loss affects the store network; issue remains unresolved.
KB resources consulted: runbooks/network-router-offline.md
Devices affected: POS terminal T1 and other networked devices across the store; WiFi is not broadcasting. Router is implicated; its asset is not verified.
Users affected: Staff devices are affected; number of users not known.
Business impact: All transaction processing has halted during peak lunch service.
Workaround: unavailable: no workaround is stated in the data.
Priority and overrides: P2 (no overrides)
Escalation reason: sop_trigger: Although filed as a POS fault and linked to a POS terminal, the router is dark and wired and wireless devices across the store have lost connectivity, matching the router-offline runbook. This is a store-wide network infrastructure failure, so escalate now; the terminal restarts do not address the router outage.
SOP trigger and evidence: network_failure ("the router light indicator is off and there is no connectivity to other networked devices in the store either")
Version coverage gap: none: the runbook covers this version
Escalated at: 2026-03-28T09:37+00:00

Trick type: miscategorized. Pass when the agent handled the trick as its type expects (agent-check.md E-cases).
