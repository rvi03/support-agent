# k9_tune: INC-00242 (K9)

Subject: POS terminal not responding - system down
Category: Wi-Fi / Network

Agent messages to the store, in order:
- [status_template] Hi, an L1 engineer will contact you about ticket SWT-BA36527F34B3 by 16:44 IST on 14 Jan.
Store replies, in order:
- none
IT actions run:
- none
Walk: runbook runbooks/network-router-offline.md, steps 
Ticket ended: status in_progress, route l1_pack, handoff reason -

## l1_pack

L1 pack for runbooks/network-router-offline.md
Issue: The ticket is categorized as POS, but the reported Wi-Fi light being off points to a Network Router issue (real category: Wi-Fi / Network). Router model and version are unavailable; the POS version does not identify the router.
Path:
- Use runbook runbooks/network-router-offline.md. Its router-offline symptoms fit the reported light status; begin with the store checks, then verify router hardware and connectivity. [runbooks/network-router-offline.md#symptoms, runbooks/network-router-offline.md#immediate-steps-first-2-minutes, runbooks/network-router-offline.md#l1-diagnosis-steps-step-1-verify-physical-hardware-status, runbooks/network-router-offline.md#l1-diagnosis-steps-step-2-check-physical-connectivity]
- If needed, continue to router-interface access and WAN/ISP diagnostics; choose resolution steps based on findings. [runbooks/network-router-offline.md#l1-diagnosis-steps-step-3-attempt-remote-access-to-router-in, runbooks/network-router-offline.md#l1-diagnosis-steps-step-4-check-wan-internet-connection-stat, runbooks/network-router-offline.md#l1-diagnosis-steps-step-5-verify-isp-connection-and-dns, runbooks/network-router-offline.md#l1-resolution-resolution-a-reboot-router-most-common-fix, runbooks/network-router-offline.md#l1-resolution-resolution-b-reset-wan-internet-configuration~1, runbooks/network-router-offline.md#l1-resolution-resolution-c-power-cycle-modem-and-router-sequ]
Known-bug fix: none — the listed known bug is a POS PIN-pad timeout, not the reported router/Wi-Fi issue.
Version warning: Router model and version are unavailable, so coverage cannot be confirmed. The runbook names NetLink NL-3000 v2.x and Cisco SG350; apply only its general steps unless the router is confirmed to match.
Already tried (skip):
- The store already restarted the POS terminal; do not repeat that attempt. This does not establish that the router was restarted.
Ask the store first:
- What is the router make/model and version, and what are the exact power and other LED statuses?
- Are the router-to-modem/WAN cables firmly connected, and is a separate modem powered with normal status lights?
- Are neighboring locations or other branches also offline?
- When did the outage begin as accurately as possible, and has the shift manager been informed?
When to escalate:
- Escalate to L2 if the router remains unresponsive: router IP cannot be pinged and web/SSH access fails, or no LEDs remain lit after the runbook's hard-reboot wait. Include LED status and confirm power is connected. [runbooks/network-router-offline.md#when-to-escalate-to-l2-escalation-criteria]
- Escalate if WAN remains disconnected/no signal after cable verification and the modem is operational; also escalate if external ping continues to fail after the L1 diagnostics and steps, or hardware-error indicators persist after boot. Contact the ISP in parallel where the runbook directs. [runbooks/network-router-offline.md#when-to-escalate-to-l2-escalation-criteria]
- The runbook calls for immediate L2 escalation for a P1 outage during its listed peak meal-service periods. This ticket is P2, and the supplied facts do not establish that this condition applies. If unresolved, the ticket goes to L2 at the escalate-by time; that time is unavailable in the supplied data. [runbooks/network-router-offline.md#when-to-escalate-to-l2-escalation-criteria]

Trick type: miscategorized. Pass when the agent handled the trick as its type expects (agent-check.md E-cases).
