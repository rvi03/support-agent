# P2 Queue access (design.md, Authorization policies; S12): IT roles see the queue
# they work. l1_agent: tickets in the L1 queue (L1 packs). l2_engineer: tickets in the
# L2 queue, and tickets waiting on an L2 approval or an L2 task. vendor_approver:
# tickets waiting on a vendor approval. Admin reads go through P6.
# Input: {"action", "subject": {"roles", ...},
#         "resource": {"assignee_queue", "pending": {"kind", "approver_role"} | null}}
package servewell.p2_queues

import rego.v1

it_roles := {"l1_agent", "l2_engineer", "vendor_approver"}

default allow := false

pending := object.get(input.resource, "pending", null)

allow if {
	input.action == "api.list_tickets"
	some role in input.subject.roles
	role in it_roles
}

allow if {
	input.action == "api.get_ticket"
	"l1_agent" in input.subject.roles
	input.resource.assignee_queue == "l1"
}

allow if {
	input.action == "api.get_ticket"
	"l2_engineer" in input.subject.roles
	input.resource.assignee_queue == "l2"
}

allow if {
	input.action == "api.get_ticket"
	"l2_engineer" in input.subject.roles
	is_object(pending)
	pending.kind == "l2_task"
}

allow if {
	input.action == "api.get_ticket"
	some role in input.subject.roles
	role in {"l2_engineer", "vendor_approver"}
	is_object(pending)
	pending.kind == "approval"
	pending.approver_role == role
}
