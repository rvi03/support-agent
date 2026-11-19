# calibration: INC-00129 (K8)

Subject: POS Terminal T1 screen frozen - customer orders blocked
Category: POS

Agent messages to the store, in order:
- [framing_template] Hi, for ticket SWT-8268A47A6009, please do the next step below and reply with what you see (for example the lights, the screen message or whether it prints).
- [step] 1. **Wait 30 seconds.** Occasional brief freezes may resolve autonomously. Do not repeatedly tap the screen.
- [framing_template] Hi, for ticket SWT-8268A47A6009, please do the next step below and reply with what you see (for example the lights, the screen message or whether it prints).
- [step] 2. **Check for system notifications.** Look for any dialog boxes or notification banners that may require dismissal (e.g., Windows Update prompts, license warnings). If found, try to dismiss with a mouse/keyboard if available.
- [framing_template] Hi, for ticket SWT-8268A47A6009, please do the next step below and reply with what you see (for example the lights, the screen message or whether it prints).
- [step] **Do NOT hold power for >10 seconds**—that forces a hard power-off and risks transaction data loss.
3. **Attempt a graceful restart.** If staff have access to a keyboard, try `Alt+F4` to close the current application, or ask them to hold the power button for 5 seconds (soft shutdown).
- [framing_template] Hi, for ticket SWT-8268A47A6009, please do the next step below and reply with what you see (for example the lights, the screen message or whether it prints).
- [step] - Ask staff to connect a USB mouse or keyboard if one is available in the store.
   - Instruct them to move the mouse or press a key (e.g., spacebar).
- [status_template] Hi, your ticket SWT-8268A47A6009 is now with our L2 support team (priority P4). They will contact you by 16:28 IST on 18 Nov.
Store replies, in order:
- I waited 30 seconds, but the order-entry screen is still frozen and not responding.
- I checked for notifications, but the order-entry screen is still frozen and not responding.
- I tried the graceful restart, but the order-entry screen is still frozen and won’t respond to keyboard or touchscreen input.
- I tried a USB mouse and pressed a key, but the order-entry screen is still frozen and unresponsive.
IT actions run:
- none
Walk: runbook runbooks/pos-screen-frozen.md, steps psf-wait (store: replied), psf-notifications (store: replied), psf-graceful-restart (store: replied), psf-mouse-test (store: replied)
Ticket ended: status escalated, route resolver, handoff reason steps_exhausted

## l2_note

Ticket ID: SWT-8268A47A6009
Executive summary: FoodTech POS Terminal POS-0058-T1 (asset verified) at counter 1 is frozen on the order-entry screen and accepts no keyboard or touchscreen input. L2 handoff is required because the runbook says to confirm an OS hang, but that step is not in approved_steps; the handoff reason is steps_exhausted, supported by “No mouse or keyboard input registers.” Priority is P4 under the fired “known issue with workaround” rule; warranty is in warranty, vendor route.
Store: SW-0058 ServeWell - OMR, OMR, Chennai (franchise)
Asset ID: POS-0058-T1
Asset type: POS Terminal (FoodTech POS FoodTech POS Terminal 1, FoodTech POS v4.2.3)
Store contact: on file (vault)
Error code or message: unavailable: no error code or message was reported; the description reports a frozen order-entry screen.
First occurrence: reported 2025-11-18T08:58+00:00
Frequency: persistent
Steps tried and outcome: 1) Basic power cycle (reported in ticket description). -> Issue persists.; 2) Waited 30 seconds (runbook psf-wait). -> Order-entry screen still frozen and not responding.; 3) Checked for notifications (runbook psf-notifications). -> Order-entry screen still frozen and not responding.; 4) Tried graceful restart (runbook psf-graceful-restart). -> Screen still frozen and would not respond to keyboard or touchscreen input.; 5) Tried USB mouse and pressed a key (runbook psf-mouse-test). -> Screen still frozen and unresponsive; no mouse or keyboard input registers.; 6) Runbook directs next step to Step 4: confirm OS hang. -> Step is not in approved_steps; handed off to L2.; 7) KB resource consulted: runbooks/pos-screen-frozen.md. -> Version coverage is marked covered for FoodTech POS v4.2.3.
KB resources consulted: runbooks/pos-screen-frozen.md
Devices affected: 1 POS terminal: POS-0058-T1.
Users affected: Store staff; number unavailable: not stated.
Business impact: Staff cannot process orders on this terminal during peak lunch hours, affecting customer service.
Workaround: unavailable: no workaround reported; the attempted power cycle and runbook steps did not resolve the freeze.
Priority and overrides: P4 (-1 known issue with workaround)
Escalation reason: steps_exhausted
Warranty: in warranty (131 days left): vendor route
Version coverage gap: none: the runbook covers this version
Escalated at: 2025-11-18T09:07+00:00

## Expected (label)

- Routing: l1_guided; escalation reason: Screen frozen issue persists after basic power cycle troubleshooting; requires advanced diagnostics or hardware intervention. Escalation flag is set and impact is high (blocking customer orders during peak hours).
- Resolution: Agent should retrieve the pos-screen-frozen runbook and guide the store through advanced troubleshooting steps (force quit applications, check system logs, perform hard reset if needed). If issue persists after guided troubleshooting, escalate to L2 with detailed diagnostics including system logs and hardware status, as this may require remote intervention or hardware replacement.
- Tricky-ticket behaviour: PASS: Agent retrieves pos-screen-frozen runbook and provides step-by-step guided troubleshooting before escalating. Agent documents troubleshooting attempts and escalates with full context. FAIL: Agent escalates immediately without attempting guided troubleshooting, or escalates without retrieving relevant runbook documentation.

## Judge's reason (score blind first, then compare)

The agent retrieved the relevant pos-screen-frozen runbook and guided the store through waiting, checking notifications, a graceful restart, and a mouse/keyboard test before escalating to L2. However, the expected advanced troubleshooting—such as force-quitting applications, checking system logs, and considering a hard reset—was not completed, and no system-log or hardware diagnostics were included in the handoff.
