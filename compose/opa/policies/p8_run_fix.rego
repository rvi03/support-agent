# P8 Run a fix (design.md; S7 build step 4; D37; S8a quote binding). itsm-actions gathers the
# facts from its own tables under a row lock (never from the caller) and asks
# this package; any `deny` reason refuses the run, and the refusal is audited.
#   1 the action is in the registry, whose version equals the one in the ticket's kb_rev
#   2 the asset is the ticket's asset and belongs to the bound store
#   3 the quote is bound: the cited section is in the ticket's runbook and kb_rev and
#     holds the quoted words (S8a); the asset's device family is one of the action's
#   4 read_only, or reversible + autonomous, runs alone; destructive or supervised needs
#     a decided, approved, unexpired (wall clock), unused approval bound to the same
#     run, ticket, asset, section, quote, action and kb_rev, from the right approver role;
#     a runbook approval line on the binding always needs one
#   S12a: (section, quote, action) is an approved IT binding without a conflict; the
#     ticket is open and its escalate-by (ticket time) has not passed
# Input: see itsm/server.py `_run_fix_facts`. A missing or null fact is refused
# (fail closed): every presence check reads the fact with object.get and a null
# default, so a missing key counts as missing (a bare `input.x == null` is
# undefined for a missing key and would let the call through).
package servewell.p8_run_fix

import rego.v1

binding_fields := ["run_id", "ticket_id", "asset_id", "section_id", "quote", "action_id", "kb_rev"]

action := input.registry.action

ticket := input.ticket

section := input.section

approval := input.approval

# ---- 1 registry ------------------------------------------------------------------

deny contains "unknown_action" if not is_object(object.get(object.get(input, "registry", {}), "action", null))

deny contains "registry_drift" if {
	action != null
	ticket != null
	ticket.registry_version != input.registry.version
}

# ---- 2 ticket, store and asset ---------------------------------------------------

deny contains "ticket_not_found" if not is_object(object.get(input, "ticket", null))

deny contains "other_store" if {
	ticket != null
	ticket.store_id != input.context.store_id
}

deny contains "not_ticket_asset" if {
	ticket != null
	input.request.asset_id != ticket.asset_id
}

deny contains "asset_not_found" if not is_object(object.get(input, "asset", null))

deny contains "asset_other_store" if {
	input.asset != null
	input.asset.store_id != input.context.store_id
}

# ---- 3 quote binding (S8a) ------------------------------------------------------
# The agent cites a section of the ticket's runbook and the exact words it acts on;
# itsm-actions reads that section in the ticket's kb_rev and checks the quote.

deny contains "no_runbook" if {
	ticket != null
	not is_string(ticket.runbook_id)
}

deny contains "section_not_in_runbook" if not is_object(object.get(input, "section", null))

deny contains "quote_not_in_section" if {
	section != null
	not section.quote_ok
}

deny contains "section_other_runbook" if {
	section != null
	ticket != null
	section.doc_id != ticket.runbook_id
}

deny contains "section_other_kb_rev" if {
	section != null
	ticket != null
	section.kb_rev != ticket.kb_rev
}

deny contains "device_family" if {
	action != null
	input.asset != null
	not input.asset.family in action.device_families
}

# ---- 4 approved binding and ticket state (S12a) ---------------------------------
# itsm-actions looks the (section, quote, action) up in bindings.yaml itself, so a
# real quote paired with another action is refused; the ticket must still be open
# and its escalate-by (ticket time, D48) not passed.

open_statuses := {"new", "in_progress", "waiting_store", "waiting_approval", "waiting_l2"}

binding := object.get(input, "binding", null)

deny contains "no_binding" if not is_object(binding)

deny contains "binding_conflict" if {
	is_object(binding)
	object.get(binding, "conflict", true) != false
}

deny contains "ticket_not_open" if {
	ticket != null
	not object.get(ticket, "status", null) in open_statuses
}

deny contains "ticket_clock_missing" if not is_number(object.get(input, "ticket_now_ns", null))

deny contains "sla_passed" if {
	ticket != null
	esc := object.get(ticket, "escalate_by_ns", null)
	is_number(esc)
	is_number(object.get(input, "ticket_now_ns", null))
	input.ticket_now_ns >= esc
}

# ---- 5 tier, autonomy and approval -----------------------------------------------

needs_approval if action.tier == "destructive"

# a runbook approval line forces approval, whatever the tier or autonomy (D109)
needs_approval if {
	is_object(binding)
	object.get(binding, "approval", true) != false
}

needs_approval if {
	action.tier == "reversible"
	input.autonomy.state != "autonomous"
}

required_approver := "vendor_approver" if {
	action.approver == "vendor"
} else := "l2_engineer"

deny contains "approval_missing" if {
	needs_approval
	not is_object(object.get(input, "approval", null))
}

# An approval id that was sent is always checked, needed or not.
deny contains "approval_not_found" if {
	input.request.approval_id != null
	not is_object(object.get(input, "approval", null))
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
	"section_id": input.request.section_id,
	"quote": input.request.quote,
	"action_id": input.request.action_id,
	"kb_rev": object.get(ticket, "kb_rev", null),
}

default allow := false

allow if count(deny) == 0
