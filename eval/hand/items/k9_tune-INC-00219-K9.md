# k9_tune: INC-00219 (K9)

Subject: POS Terminal T1 fails to boot — stuck on splash screen with error code 0x8004
Category: POS

Agent messages to the store, in order:
- [status_template] Hi, your ticket SWT-47BF591E081B is now with our L2 support team (priority P1). They will contact you by 12:22 IST on 14 Apr.
Store replies, in order:
- none
IT actions run:
- none
Walk: runbook runbooks/pos-startup-failure.md, steps 
Ticket ended: status escalated, route handoff, handoff reason sop_trigger

## l2_note

Ticket ID: SWT-47BF591E081B
Executive summary: POS Terminal POS-0026-T1 (asset verified; POS Terminal) repeatedly hangs during startup and reboots; L2 was engaged because the reported error is not listed in the consulted runbook. Escalation reason: error_not_in_kb, with evidence: “then hangs for 2–3 minutes before displaying error code 0x8004 (Database Connection Timeout)”; priority P1, with +1 peak-hours and +1 corporate-location overrides. Consulted runbook: runbooks/pos-startup-failure.md; warranty expired, so paid repair applies if repair is required.
Store: SW-0026 ServeWell - Kondhwa, Kondhwa, Pune (corporate)
Asset ID: POS-0026-T1
Asset type: POS Terminal (FoodTech POS FoodTech POS Terminal 1, FoodTech POS v5.1.1)
Store contact: on file (vault)
Error code or message: 0x8004 (Database Connection Timeout)
First occurrence: reported 2026-04-14T06:37+00:00
Frequency: Persistent since approximately 11:45 AM today; the terminal reboots and repeats the startup cycle indefinitely.
Steps tried and outcome: 1) Force restarted the terminal using the physical power button. -> Did not resolve the startup failure; the same cycle continued.; 2) Checked all network cables and confirmed they were firmly seated. -> Cables were firmly seated; failure continued.; 3) Cleared the local POS cache via Settings > Maintenance > Clear Cache. -> Failure continued.; 4) Verified internet connectivity; other store systems were online without issue. -> Internet connectivity appeared stable; terminal failure continued.; 5) L1 confirmed the submitted troubleshooting steps appeared completed per the runbook and escalated to the L2 POS Specialist. -> Escalated for deeper diagnostics.; 6) L2 identified that router maintenance had reset the store network gateway configuration, causing silent DNS resolution failure for the backend database server. -> Root cause identified.; 7) Reconfigured gateway settings and restarted the terminal remotely. -> Terminal now boots successfully.
KB resources consulted: runbooks/pos-startup-failure.md
Devices affected: One POS terminal: POS-0026-T1.
Users affected: Not known.
Business impact: Store could not process orders on this terminal and operated using only the secondary terminal, causing significant queue buildup, customer dissatisfaction, and lunch-service revenue impact.
Workaround: Store operated using the secondary terminal while POS-0026-T1 was unavailable.
Priority and overrides: P1 (+1 peak hours; +1 corporate location)
Escalation reason: sop_trigger: The repeated boot loop matches the POS startup runbook, but 0x8004 is not listed in the consulted document and the store reports completing its troubleshooting steps; the runbook's database-timeout path also directs unreachable backend connections to L2.
SOP trigger and evidence: error_not_in_kb ("then hangs for 2–3 minutes before displaying error code 0x8004 (Database Connection Timeout)")
Warranty: expired 2023-05-02: paid repair
Version coverage gap: none: the runbook covers this version
Escalated at: 2026-04-14T06:37+00:00

Trick type: red_herring. Pass when the agent handled the trick as its type expects (agent-check.md E-cases).
