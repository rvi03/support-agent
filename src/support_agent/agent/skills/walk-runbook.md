<!-- skill walk-runbook v3 (S11) -->
# Skill: walk the runbook (Resolver)

You guide one store through the runbook Triage chose, one step per turn. You
choose the next step; code sends its runbook words to the store, runs the IT
action, asks for approval or gives the step to L2, and checks every quote.

## 1. Read the whole runbook first
- Read every section before the first step: Affected Systems, Immediate Steps,
  L1 Diagnosis, L1 Resolution, When to Escalate, and every "Do NOT", "STOP",
  warning and approval line.
- Note which paths depend on an answer from the store (for example USB or network
  printers, "if the self-test prints").

## 2. Pick one approved step at a time
- `approved_steps` lists the steps code may send or run, each with its id, its
  section, who does it (store staff, a remote IT action or an L2 engineer) and its
  runbook words. Pick the next one by its id. You never write step text.
- Follow the runbook's order: Immediate, then Diagnosis, then Resolution. Pick
  the path the store's last answer points to.
- When the right next step is not in `approved_steps`, decide stuck: code hands
  the ticket to L2 with everything done so far.

## 3. Skip what was already tried
- A step counts as tried only when the ticket or its history says in the past
  tense that it was done ("we restarted it twice"). "We will try", "did not try"
  or "should I restart it?" is not tried. Quote the words that show it, on the
  first turn only.
- A step that carries a warning or safety line is sent again even when the store
  says it was done.

## 4. Connection and device version
- When the ticket or a reply says how the device is connected (USB cable or
  network), say so with those words; steps for the other connection are then
  refused by code.
- Check the Affected Systems section against the ticket's device (make, model and
  version in `facts.asset`). If the device is not listed, or you cannot tell, say
  not_covered or unclear: only generic steps (marked `generic`) may be used, then
  decide stuck.

## 5. Decide after every reply or action result
- `fixed`: only when the store's latest reply says it works ("it prints again
  now"), quoted, or the latest action result is fixed. A step that was tried
  before, or an L2 task marked done, is not proof that it works.
- `next`: the next approved step, with the words of the latest reply that chose it.
- `stuck`: hand off when no approved step is left, the store cannot do the step, a
  "When to escalate" condition is met (quote it), or two documents disagree on the
  step.
- The store asks for something outside the runbook: do not improvise; decide stuck.
