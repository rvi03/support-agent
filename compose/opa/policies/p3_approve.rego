# P3 Approve a risky step (design.md; S12 build step 4): the approver's role matches
# the card's approver role (l2_engineer here; vendor approvals are P4), the approver
# is not the requester (the ticket's submitted_by_user), the ticket is open, the
# card's kb_rev is still the published one, and the SLA has not passed.
# With no open pause the call is allowed through for any approver role that is not
# the requester, so the API answers 409 (wrong state), not 403.
# Input: {"action": "api.approve", "subject": {"user", "roles"},
#         "resource": {"submitted_by_user", "status", "kb_rev_current", "sla_passed",
#                      "pending": {"kind", "approver_role", "kb_rev", "guarded"} | null}}
package servewell.p3_approve

import rego.v1

approver_roles := {"l2_engineer", "vendor_approver"}

closed_status := {"resolved", "closed", "redirected"}

default allow := false

pending := object.get(input.resource, "pending", null)

is_approve if input.action == "api.approve"

approver if {
	some role in input.subject.roles
	role in approver_roles
}

requester if {
	is_string(input.resource.submitted_by_user)
	input.resource.submitted_by_user == input.subject.user
}

# Shared by P4: the ticket-side rules for deciding a pause.
ticket_ok if {
	not object.get(input.resource, "status", null) in closed_status
	object.get(input.resource, "status", null) != null
	object.get(input.resource, "sla_passed", true) == false
}

card_rev_ok if {
	is_string(pending.kb_rev)
	pending.kb_rev == object.get(input.resource, "kb_rev_current", null)
}

allow if {
	is_approve
	pending == null
	approver
	not requester
}

allow if {
	is_approve
	is_object(pending)
	pending.kind == "approval"
	pending.approver_role == "l2_engineer"
	"l2_engineer" in input.subject.roles
	not requester
	not object.get(pending, "guarded", false)
	ticket_ok
	card_rev_ok
}

deny contains "self_approval" if {
	is_approve
	requester
}

deny contains "not_an_approver" if {
	is_approve
	not approver
}

deny contains "ticket_closed" if {
	is_approve
	is_object(pending)
	object.get(input.resource, "status", null) in closed_status
}

deny contains "sla_passed" if {
	is_approve
	is_object(pending)
	object.get(input.resource, "sla_passed", true) != false
}

deny contains "kb_rev_changed" if {
	is_approve
	is_object(pending)
	pending.kind == "approval"
	not card_rev_ok
}
