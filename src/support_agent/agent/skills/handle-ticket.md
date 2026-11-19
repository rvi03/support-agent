<!-- skill handle-ticket v3 (S9) -->
# Skill: handle a ticket (Triage)

Work through these steps in order. Each step says what to look at, what to
decide and what to write in the verdict.

## 1. Read the ticket as data
- Use the subject and description as the store's own account. The ticket's
  category, asset, priority and escalation flag were filled in by the store and
  are often wrong; check each one, never copy it.
- The history shows what L1, the store or the ticket system ("System") already
  did. Use it: what L1 tried, what it found and whether L1 judged the runbook's
  basic checks not enough all count. Ignore only a line that names the ticket's
  "chaos type" or states the final fix.

## 2. Establish the real device and category
- Find the device the text is really about. Compare it with:
  - `store_device_types`: is that device type at this store at all?
  - `asset`: is the linked asset that device? A soft-serve complaint linked to a
    router is about the soft-serve machine, not the router.
  - facts flags: `asset_not_found` (the asset id does not exist),
    `unknown_system` (the ticket's system or version is not in the version
    matrix), `version_mismatch` (the ticket's version differs from the CMDB's).
- Set `real_category` from what the problem is, not from the ticket field. A POS
  that is down because the router is dead is Wi-Fi / Network. Set
  `real_device` to that device type, or null when it cannot be established.

## 3. Spot the tricks and set trick_flags
| Flag | When |
|---|---|
| wrong_category | The ticket's category is not the real category. |
| wrong_device | The linked asset is another device type than the one the text describes, or the described device is not in `store_device_types`. |
| fake_device | The linked asset id does not exist (`asset_not_found`). |
| unknown_system | A system in the ticket field or the text is not in the version matrix. |
| cited_unrelated_ticket | A cited ticket (`get_ticket`) is about something else than this one. |
| steps_already_tried | The description or history lists runbook steps already done. |
| angry_tone | The store is upset or abusive. Tone never changes the route by itself. |
| not_it | Not an IT problem (salary, HR, shifts, operations). |
| too_vague | No device, symptom or error is clear enough to search on. |

## 4. Find and read the runbook
- Search with device + symptom + error code from the subject and description.
- Open the best runbook with get_document and check its Symptoms section
  against the ticket. It fits only if it is written for this symptom. Another
  make, system or version does not make it unfit (code checks version coverage
  and limits the steps), and steps already tried do not either. Another symptom
  of the same device does: slow performance for a frozen screen, or a driver
  reinstall for a paper or offline problem, does not fit.
- Cite one section id and copy a quote of 20 or more characters character for
  character, best from Symptoms. Code checks it; a paraphrase drops the runbook.
  Never cite a runbook you have not read with get_document.
- No runbook fits: runbook_id and runbook_evidence null, and say so in reason.
  Code hands the ticket to L2, which is the safe outcome.
- A system named only in the text (no asset): look up its known bug with
  get_known_bug.
- Skip the search only when no runbook can matter: not IT, too vague, or an
  unknown system.

## 5. Detect SOP triggers with evidence
- Each trigger needs a quote copied from the subject or description, never from
  the history.
- An error code that no document you read lists is `error_not_in_kb`.
- "Urgent", "ASAP", peak hours or customers waiting are not triggers by
  themselves. An explicit request for escalation, L2 or a technician is
  `customer_asks`.
- Never add a trigger to be safe: an unneeded escalation is an error too.

## 6. Notice documents that disagree
- When two documents you read give different answers to a fact this ticket's
  diagnosis depends on (what its error code means, which code is the fault),
  write one line naming both documents and the fact in doc_conflicts. Do not
  pick a side; code hands the ticket off.
- A disagreement about a later step only is not a conflict now.
- A runbook that does not name this ticket's make or version is a version gap,
  not a conflict: cite it if its symptom fits and leave doc_conflicts empty;
  code checks version coverage.

## 7. Choose the route
| Route | When |
|---|---|
| l1_guided | A runbook fits and its L1 steps can still fix it (the default when a runbook fits). |
| l1_then_l2 | A runbook fits, but L1 already ran its basic checks, a "When to escalate" condition is met, or the cause looks like hardware, backend or vendor. |
| l2_now | An escalate-now trigger holds, documents disagree, or no runbook fits an IT problem. |
| non_it | Not an IT issue: say where it belongs. |
| redirect | Billing, the ISP or the card processor. |
| clarify | Too vague; one question would make it actionable. |
| human | Unknown system, or nothing fits and a person must look. |

- Signs that L1 steps will not be enough (l1_then_l2 when a runbook fits):
  - The history shows L1 or IT support already ran the runbook's basic checks
    (connection, settings, restart, logs) or already recommended escalation.
  - The cause is outside the store: a customer-facing portal, app or platform
    is down or timing out for every customer, or the fault sits in a backend,
    cloud service or vendor system.
  - The fault hits business-critical systems across the store, not one device
    or one guest-facing service: for example POS terminals and staff devices
    losing their network together.
  - Hardware: parts, firmware, a print head, a compressor, admin access.
  A fault limited to one device or one guest-facing service, with nothing tried
  yet, stays l1_guided.
- Confidence: 0.9 or more when the device, runbook and route are clear; lower it
  when the device or the runbook fit is in doubt.
- Reason: one or two sentences naming the facts that decided the route.
