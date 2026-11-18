# P8 Run a fix (design.md; S7 build step 4; D37, D51). itsm-actions gathers the
# facts from its own tables under a row lock (never from the caller) and asks
# this package; any `deny` reason refuses the run, and the refusal is audited.
#   1 the action is in the registry, whose version equals the one in the ticket's kb_rev
#   2 the asset is the ticket's asset and belongs to the bound store
#   3 the step is bound: read by (ticket kb_rev, ticket runbook, step id); same action;
#     the asset's device family is one of the action's
#   4 prohibitions first: guard, l2_only, secret or conflict -> refused whatever the approval
#   5 read_only, or reversible + autonomous with no approval/destructive tag, runs alone;
#     otherwise a decided, approved, unexpired (wall clock), unused approval bound to
#     the same run, ticket, asset, step, action and kb_rev, from the right approver role
# Input: see itsm/server.py `_run_fix_facts`.
package servewell.p8_run_fix

import rego.v1

prohibited_flags := {"guard", "l2_only", "secret", "conflict"}

binding_fields := ["run_id", "ticket_id", "asset_id", "step_id", "action_id", "kb_rev"]

action := input.registry.action

ticket := input.ticket

step := input.step

approval := input.approval

flags := {f | some f in step.flags}

# ---- 1 registry ------------------------------------------------------------------

deny contains "unknown_action" if action == null

deny contains "registry_drift" if {
	action != null
	ticket != null
	ticket.registry_version != input.registry.version
}

# ---- 2 ticket, store and asset ---------------------------------------------------

deny contains "ticket_not_found" if ticket == null

deny contains "other_store" if {
	ticket != null
	ticket.store_id != input.context.store_id
}

deny contains "not_ticket_asset" if {
	ticket != null
	input.request.asset_id != ticket.asset_id
}

deny contains "asset_not_found" if input.asset == null

deny contains "asset_other_store" if {
	input.asset != null
	input.asset.store_id != input.context.store_id
}

# ---- 3 step binding --------------------------------------------------------------

deny contains "no_runbook" if {
	ticket != null
	not is_string(ticket.runbook_id)
}

deny contains "step_not_found" if step == null

deny contains "step_other_action" if {
	step != null
	step.action_id != input.request.action_id
}

deny contains "step_other_runbook" if {
	step != null
	ticket != null
	step.doc_id != ticket.runbook_id
}

deny contains "step_other_kb_rev" if {
	step != null
	ticket != null
	step.kb_rev != ticket.kb_rev
}

deny contains "step_not_it" if {
	step != null
	step.team != "it"
}

deny contains "device_family" if {
	action != null
	input.asset != null
	not input.asset.family in action.device_families
}

# ---- 4 prohibitions (before tier or approval, D51) --------------------------------

deny contains sprintf("prohibited_step:%s", [f]) if {
	some f in flags
	f in prohibited_flags
}

# ---- 5 tier, autonomy and approval -----------------------------------------------

needs_approval if action.tier == "destructive"

needs_approval if {
	action.tier == "reversible"
	input.autonomy.state != "autonomous"
}

needs_approval if "approval" in flags

needs_approval if "destructive" in flags

required_approver := "vendor_approver" if {
	step.approver == "vendor"
} else := "vendor_approver" if {
	action.approver == "vendor"
} else := "l2_engineer"

deny contains "approval_missing" if {
	needs_approval
	approval == null
}

# An approval id that was sent is always checked, needed or not.
deny contains "approval_not_found" if {
	input.request.approval_id != null
	approval == null
}

deny contains "approval_not_approved" if {
	approval != null
	approval.decision != "approved"
}

deny contains "approval_expired" if {
	approval != null
	input.now_ns >= approval.expires_ns
}

deny contains "approval_used" if {
	approval != null
	approval.used
}

deny contains sprintf("approval_binding:%s", [f]) if {
	approval != null
	some f in binding_fields
	approval[f] != expected_binding[f]
}

deny contains "approval_role" if {
	approval != null
	approval.approver_role != required_approver
}

expected_binding := {
	"run_id": input.context.run_id,
	"ticket_id": input.context.ticket_id,
	"asset_id": input.request.asset_id,
	"step_id": input.request.step_id,
	"action_id": input.request.action_id,
	"kb_rev": object.get(ticket, "kb_rev", null),
}

default allow := false

allow if count(deny) == 0
