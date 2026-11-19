# k9_tune: INC-00279 (K9)

Subject: StarMC Print v3.0 printer PRN-0054-P1 not detected on POS terminal
Category: Printers

Agent messages to the store, in order:
- [framing_template] Hi, for ticket SWT-A59C2EEFFC0D, please do the next step below and reply with what you see (for example the lights, the screen message or whether it prints).
- [step] 2. **Printer Self-Test**
   - Press and hold the **FEED button** on the printer for 3–5 seconds to initiate self-test
   - Verify paper loads and prints test pattern (confirms hardware is functional)
   - If self-test prints successfully, issue is driver or connectivity related
- [framing_template] Hi, for ticket SWT-A59C2EEFFC0D, please do the next step below and reply with what you see (for example the lights, the screen message or whether it prints).
- [step] 3. **Restart POS Application**
   - Close ServeWell POS completely
   - Wait 10 seconds
   - Reopen ServeWell POS and check if printer status updates to "Online"
- [framing_template] Hi, for ticket SWT-A59C2EEFFC0D, please do the next step below and reply with what you see (for example the lights, the screen message or whether it prints).
- [step] - Disconnect USB cable from printer
   - Wait 5 seconds
   - Reconnect USB cable
   - Wait 10 seconds for Windows to detect device
- [status_template] Hi, the next step on ticket SWT-A59C2EEFFC0D is a remote IT action that needs IT approval first. We will update you as soon as it is decided.
- [status_template] Hi, your ticket SWT-A59C2EEFFC0D is now with our L2 support team (priority P2). They will contact you by 10:54 IST on 18 Nov.
Store replies, in order:
- I held the FEED button for 3–5 seconds as requested, but the printer is still not detected.
- I closed ServeWell POS, waited 10 seconds, and reopened it, but the printer is still offline.
- I disconnected and reconnected the USB cable as instructed, but the printer still isn’t detected by Windows.
IT actions run:
- check_printer_recognition (read_only): no_change: check_printer_recognition ran; no change.
- check_device_manager_status (read_only): no_change: check_device_manager_status ran; no change.
- restart_print_spooler (reversible): no_change: restart_print_spooler ran; no change.
- check_printer_driver_version (read_only): no_change: check_printer_driver_version ran; no change.
Walk: runbook runbooks/printer-offline.md, steps po-self-test (store: replied), po-restart-pos-app (store: replied), po-usb-recognition (action: no_change), po-usb-reconnect (store: replied), po-usb-device-manager (action: no_change), po-usb-spooler-check (approval: done), po-usb-spooler-check (action: no_change), po-usb-driver-version (action: no_change)
Ticket ended: status escalated, route resolver, handoff reason steps_exhausted

## l2_note

Ticket ID: SWT-A59C2EEFFC0D
Executive summary: Receipt Printer (asset PRN-0054-P1), StarMC Print v2 v3.0, at Thane West is not detected by the POS; the issue was first reported at approximately 09:45 IST. Handoff reason is steps_exhausted: runbook checks did not restore detection, and the walk ended with “Driver installation fails with error message”; ticket history also records a later statement that the actual issue was a missing November salary deposit, which conflicts with the printer triage. Priority P2; warranty is in force (vendor route); runbook consulted: runbooks/printer-offline.md; no SOP triggers are listed.
Store: SW-0054 ServeWell - Thane West, Thane West, Mumbai (franchise)
Asset ID: PRN-0054-P1
Asset type: Receipt Printer (StarMC Print v2 StarMC Print v2, StarMC Print v2 v3.0)
Store contact: on file (vault)
Error code or message: Device PRN-0054-P1 offline - no active connection detected.
First occurrence: reported 2025-11-18T04:54+00:00
Frequency: Persistent since approximately 09:45 IST on the day reported; exact recurrence history unavailable.
Steps tried and outcome: 1) Store verified printer was powered on and showing no error lights. -> No error lights; printer still not detected.; 2) Store checked that the USB cable was firmly connected to the POS terminal. -> Cable appeared firmly connected; issue persisted.; 3) Store restarted the POS system twice. -> Printer still did not appear in Device Manager.; 4) Store attempted to reinstall printer drivers from the StarMC suite. -> System could not locate the hardware.; 5) Store power-cycled the printer and terminal. -> Issue persisted.; 6) Store checked cable connections and reviewed Device Manager logs. -> Issue persisted; no further log findings provided.; 7) L1 requested remote access to run diagnostic logs and confirm hardware detection status. -> Remote session was established; no diagnostic-log result is recorded.; 8) Store held the FEED button for 3–5 seconds (po-self-test). -> Printer still not detected.; 9) Store closed ServeWell POS, waited 10 seconds, and reopened it (po-restart-pos-app). -> Printer still offline.; 10) Ran check_printer_recognition (po-usb-recognition). -> No change.; 11) Store disconnected and reconnected the USB cable (po-usb-reconnect). -> Printer still not detected by Windows.; 12) Ran check_device_manager_status (po-usb-device-manager). -> No change.; 13) Restarted the print spooler with approval (po-usb-spooler-check). -> Action completed; no change.; 14) Ran check_printer_driver_version (po-usb-driver-version). -> No change.; 15) L1 advised the submitter to contact HR after the submitter described a missing November payroll salary deposit during chat. -> Escalation for proper categorization recorded; no resolution for the printer is recorded.
KB resources consulted: runbooks/printer-offline.md
Devices affected: One receipt printer, asset PRN-0054-P1; the POS terminal is also involved in the connection checks. No other affected devices reported.
Users affected: Not quantified; kitchen operations are affected.
Business impact: Store reports that order tickets cannot be printed, causing delays in food preparation.
Workaround: unavailable: no workaround reported.
Priority and overrides: P2 (no overrides)
Escalation reason: steps_exhausted
Warranty: in warranty (771 days left): vendor route
Version coverage gap: none; the runbook version coverage is marked covered for USB.
Escalated at: 2025-11-18T05:02+00:00

Trick type: misdirection. Pass when the agent handled the trick as its type expects (agent-check.md E-cases).
