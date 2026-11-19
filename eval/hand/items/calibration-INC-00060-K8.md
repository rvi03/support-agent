# calibration: INC-00060 (K8)

Subject: POS terminal T1 screen frozen - unable to process orders
Category: POS

Agent messages to the store, in order:
- [framing_template] Hi, for ticket SWT-E6AAB09E581E, please do the next step below and reply with what you see (for example the lights, the screen message or whether it prints).
- [step] 1. **Wait 30 seconds.** Occasional brief freezes may resolve autonomously. Do not repeatedly tap the screen.
- [framing_template] Hi, for ticket SWT-E6AAB09E581E, please do the next step below and reply with what you see (for example the lights, the screen message or whether it prints).
- [step] 2. **Check for system notifications.** Look for any dialog boxes or notification banners that may require dismissal (e.g., Windows Update prompts, license warnings). If found, try to dismiss with a mouse/keyboard if available.
- [framing_template] Hi, for ticket SWT-E6AAB09E581E, please do the next step below and reply with what you see (for example the lights, the screen message or whether it prints).
- [step] **Do NOT hold power for >10 seconds**—that forces a hard power-off and risks transaction data loss.
3. **Attempt a graceful restart.** If staff have access to a keyboard, try `Alt+F4` to close the current application, or ask them to hold the power button for 5 seconds (soft shutdown).
- [status_template] Hi, your ticket SWT-E6AAB09E581E is now with our L2 support team (priority P4). They will contact you by 10:46 IST on 21 Nov.
Store replies, in order:
- I waited 30 seconds, but the screen is still frozen on the last order-entry screen.
- I checked as requested, but it’s still frozen on the order screen and won’t accept input.
- I tried the 5-second soft shutdown, but the screen is still frozen and not accepting input.
IT actions run:
- none
Walk: runbook runbooks/pos-screen-frozen.md, steps psf-wait (store: replied), psf-notifications (store: replied), psf-graceful-restart (store: replied)
Ticket ended: status escalated, route resolver, handoff reason version_not_covered

## l2_note

Ticket ID: SWT-E6AAB09E581E
Executive summary: POS Terminal POS-0071-T1 is frozen on the last order-entry screen and accepts no keyboard or touch input. It is with L2 because OrbitPOS v2.0 is not covered by the runbook; the handoff records that only generic steps are permitted and all approved generic immediate steps have been completed. Priority is P4 under the recorded known-issue-with-workaround rule; the asset is in warranty, so the vendor route applies.
Store: SW-0071 ServeWell - Dadar, Dadar, Mumbai (franchise)
Asset ID: POS-0071-T1
Asset type: POS Terminal (OrbitPOS OrbitPOS Terminal 1, OrbitPOS v2.0)
Store contact: on file (vault)
Error code or message: unavailable: no error code or message was reported
First occurrence: reported 2025-11-21T03:16+00:00
Frequency: persistent: the screen remained frozen after the reported and guided steps
Steps tried and outcome: 1) Soft reboot by holding the power button (description). -> Screen remained frozen on the same display.; 2) Waited 30 seconds (runbook psf-wait). -> Screen remained frozen on the last order-entry screen.; 3) Checked notifications (runbook psf-notifications). -> Still frozen on the order screen and would not accept input.; 4) Tried the 5-second soft shutdown (runbook psf-graceful-restart). -> Screen remained frozen and would not accept input.; 5) Checked runbook version coverage. -> OrbitPOS v2.0 is not listed in Affected Systems; only generic steps are permitted, and all approved generic Immediate Steps have been completed.
KB resources consulted: runbooks/pos-screen-frozen.md
Devices affected: One POS terminal: POS-0071-T1.
Users affected: unavailable: the number or roles of users affected were not reported
Business impact: Order processing at the main counter is impacted during peak breakfast service.
Workaround: unavailable: no workaround was reported
Priority and overrides: P4 (-1 known issue with workaround)
Escalation reason: version_not_covered
Warranty: in warranty (0 days left): vendor route
Version coverage gap: OrbitPOS v2.0 is not covered by runbooks/pos-screen-frozen.md. Escalation reason: version_not_covered; the runbook walk states, “OrbitPOS v2.0, which is not listed in Affected Systems. Only generic steps are permitted.”
Escalated at: 2025-11-21T03:22+00:00

## Expected (label)

- Routing: l1_guided; escalation reason: -
- Resolution: Follow the pos-screen-frozen runbook which should include: (1) verify power state and attempt hard reboot by disconnecting power for 30 seconds, (2) check for stuck processes in OrbitPOS v2.0 and force-quit if needed, (3) restart the POS application, and (4) verify the terminal is accepting input and can process test transactions. If these steps fail, escalate to L2.
- Tricky-ticket behaviour: PASS: Agent retrieves pos-screen-frozen.md runbook and guides the store staff through troubleshooting steps in logical order (power cycling, process checking, application restart). Agent collects confirmation that soft reboot was already attempted and escalates appropriately if hard reboot and application restart do not resolve the issue. FAIL: Agent skips runbook retrieval, provides generic advice without reference to OrbitPOS-specific procedures, fails to distinguish between soft and hard reboot, or immediately escalates without attempting guided troubleshooting.

## Judge's reason (score blind first, then compare)

The agent retrieved the POS screen-frozen runbook and tried a wait, notification check, and soft shutdown, then escalated after the store confirmed the screen remained frozen. However, it skipped the expected 30-second power disconnect, OrbitPOS v2.0 process check/force-quit, and POS application restart, so escalation occurred before the required troubleshooting was completed.
