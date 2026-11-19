# P4 Vendor steps and L2 tasks (design.md; S12 build step 4; D51): a vendor approval
# card is decided only by vendor_approver, an L2 task only by l2_engineer, both under
# the P3 rules (not the requester, ticket open, SLA not passed; kb_rev for cards).
# A guarded step is never approvable by any role.
# Input: as P3.
package servewell.p4_vendor_l2

import rego.v1

import data.servewell.p3_approve

default allow := false

pending := object.get(input.resource, "pending", null)

allow if {
	p3_approve.is_approve
	is_object(pending)
	pending.kind == "approval"
	pending.approver_role == "vendor_approver"
	"vendor_approver" in input.subject.roles
	not p3_approve.requester
	not object.get(pending, "guarded", false)
	p3_approve.ticket_ok
	p3_approve.card_rev_ok
}

allow if {
	p3_approve.is_approve
	is_object(pending)
	pending.kind == "l2_task"
	"l2_engineer" in input.subject.roles
	not p3_approve.requester
	p3_approve.ticket_ok
}

deny contains "guarded_never_approvable" if {
	p3_approve.is_approve
	is_object(pending)
	object.get(pending, "guarded", false) == true
}

deny contains "wrong_approver_role" if {
	p3_approve.is_approve
	is_object(pending)
	pending.kind == "approval"
	not pending.approver_role in input.subject.roles
}

deny contains "l2_task_needs_l2_engineer" if {
	p3_approve.is_approve
	is_object(pending)
	pending.kind == "l2_task"
	not "l2_engineer" in input.subject.roles
}
