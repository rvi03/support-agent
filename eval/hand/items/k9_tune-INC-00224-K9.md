# k9_tune: INC-00224 (K9)

Subject: Soft serve machine motor overload alarm triggering intermittently
Category: Soft Serve

Agent messages to the store, in order:
- [status_template] Hi, an L1 engineer will contact you about ticket SWT-A1BD5BC8EC9B by 18:43 IST on 03 Dec.
Store replies, in order:
- none
IT actions run:
- none
Walk: runbook runbooks/soft-serve-motor-alarm.md, steps 
Ticket ended: status in_progress, route l1_pack, handoff reason -

## l1_pack

L1 pack for runbooks/soft-serve-motor-alarm.md
Issue: Real issue: intermittent motor overload alarm on a Soft Serve Machine. The ticket links a Cisco SG350 network router, and store inventory lists no soft-serve machine; confirm the actual machine and its make/model. The reported Cisco version is not the soft-serve machine version.
Path:
- Use runbooks/soft-serve-motor-alarm.md: the motor alarm matches the listed symptom. Stop the machine and listen for warning noises before continuing. [runbooks/soft-serve-motor-alarm.md#symptoms, runbooks/soft-serve-motor-alarm.md#immediate-steps-first-2-minutes]
- If safe to continue, verify and record the exact error code and first-occurrence time; check mix consistency and available temperatures; inspect the motor and paddle; then check the mixing chamber for obstructions. [runbooks/soft-serve-motor-alarm.md#l1-diagnosis-steps-step-1-verify-error-code, runbooks/soft-serve-motor-alarm.md#l1-diagnosis-steps-step-2-check-mix-viscosity, runbooks/soft-serve-motor-alarm.md#l1-diagnosis-steps-step-3-perform-visual-inspection, runbooks/soft-serve-motor-alarm.md#l1-diagnosis-steps-step-4-check-for-mechanical-obstructions]
- Choose a resolution path only if its stated conditions match: high mix viscosity with normal temperatures (A), normal viscosity with incorrect temperatures (B), or no grinding and free-moving parts with the alarm persisting (C). [runbooks/soft-serve-motor-alarm.md#l1-resolution-resolution-path-a-high-mix-viscosity-most-comm, runbooks/soft-serve-motor-alarm.md#l1-resolution-resolution-path-b-temperature-sensor-anomaly, runbooks/soft-serve-motor-alarm.md#l1-resolution-resolution-path-c-motor-reset-only-if-no-grind]
Known-bug fix: none — the Cisco SG350 15.2.1 is the linked router, not the reported soft-serve device; the supplied bug record has no patch and does not establish a soft-serve bug.
Version warning: The soft-serve machine make, model, and version are unavailable. This runbook covers CreamTech SC-300 v2.1+, v3.0, v3.1 and FrostyPro 800 v1.8+, v2.0, v2.1. Confirm coverage; until then, only general steps apply. The reported Cisco version does not establish soft-serve version coverage.
Already tried (skip):
- The store reports resetting the circuit breaker twice; do not repeat this as a new step. The runbook's motor-reset procedure is separate and has not been reported as tried.
- The store reports clearing visible obstructions from the motor fan; do not repeat that same check. The runbook's mixing-chamber obstruction check is not confirmed as completed.
Ask the store first:
- What is the soft-serve machine's make, model, and version? The linked asset is a router and store inventory does not list a soft-serve machine.
- Is there grinding, squealing, or rattling from the motor or chamber?
- Is there a burnt smell or visible smoke?
- Does the motor respond to the power-on command? Has it failed to respond after two attempts?
- Is the mix visibly solid or crystallized?
When to escalate:
- Escalate immediately for grinding, squealing, or rattling; burnt smell or visible smoke; or a motor that fails to respond after two attempts. [runbooks/soft-serve-motor-alarm.md#when-to-escalate-to-l2-escalate-immediately-critical]
- Escalate after diagnostics if the error persists after all L1 resolution steps, the paddle will not rotate freely or grinds, temperatures remain out of range after soft reset, or there are 3 or more motor overload errors within 1 hour. Collect the runbook's requested error, timing, mix, temperature, noise, maintenance, attempted-step, serial-number, and location details. [runbooks/soft-serve-motor-alarm.md#when-to-escalate-to-l2-escalate-after-diagnostic-steps-high-, runbooks/soft-serve-motor-alarm.md#when-to-escalate-to-l2-information-to-collect-before-escalat]
- If not fixed by the ticket's escalate-by time, send it to L2. The escalate-by time is unavailable: it is not provided in the ticket data. [runbooks/soft-serve-motor-alarm.md#when-to-escalate-to-l2-escalate-after-diagnostic-steps-high-]

Trick type: red_herring. Pass when the agent handled the trick as its type expects (agent-check.md E-cases).
