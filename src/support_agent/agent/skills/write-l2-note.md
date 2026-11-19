<!-- skill write-l2-note v1 (S9) -->
# Skill: write the L2 note (Handoff)

You write the internal note L2 reads when a ticket is handed over. Use only the
facts in your data (ticket, facts, triage verdict, steps done and their
results). Never invent a step, result, code or contact.

## Mandatory fields (escalation SOP, Required Information Checklist)
Fill every field; write "not known" when the data does not hold it.
| Field | From |
|---|---|
| Executive summary | Two or three sentences: device, symptom, why it is with L2 now. |
| Asset ID and asset type | The linked asset if it is the real device; otherwise the real device and "asset not verified". |
| Error code or message | Exactly as the store reported it. |
| First occurrence and frequency | From the description (one-time, intermittent, persistent). |
| Steps already tried and outcome | Each step from the history, the description and this run, with its result. |
| KB resources consulted | The runbook and documents read, by doc id. |
| Store impact | Devices and users affected, business impact as stated by the store. |
| Priority and why | The SOP priority code computed, with the overrides it applied. |
| Escalation reason | The reason code and the SOP trigger with its quoted evidence. |
| Warranty | In warranty: vendor route. Expired: paid repair. |

## Also include when present
- Version coverage gap: the runbook does not cover the device's version.
- Document conflicts: both documents and the fact they disagree on.
- Unknown system: say it is not in the version matrix and needs a person.

## Style
- Plain, short lines; no greeting; no names or phone numbers (code adds the
  contact).
- Never include a PIN, password or a [SECRET] marker.
