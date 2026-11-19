<!-- skill write-l1-pack v1 (S9) -->
# Skill: write the L1 pack (Group B, human L1)

You write the brief a human L1 engineer uses to work a Group B ticket (Online
Orders, Network, Soft Serve, Kiosks). Use only the facts in your data and the
chosen runbook. Never invent a step, a path or a fix.

## Sections
1. What the issue really is: real device and category, and any trick found
   (wrong category, wrong or missing asset, version mismatch).
2. Which runbook and path fit, and why: name the runbook doc id and the section
   ids of the path that matches the symptom.
3. Known-bug fix first when the device's version matches a known bug with a
   patch.
4. Version warning: say so when the runbook does not cover the device's
   version; then only the general steps apply.
5. Already tried: steps from the history and the description, so L1 skips them.
6. Ask the store first: the questions the runbook needs answered before its
   first branching step.
7. When to escalate: the runbook's own conditions for this ticket, and that the
   ticket goes to L2 at the escalate-by time if it is not fixed.

## Style
- Short bullet lines; section ids exactly as in the runbook.
- No names, phone numbers, PINs, passwords or [SECRET] markers.
