package servewell.p2_queues_test

import rego.v1

import data.servewell.p2_queues

l1 := {"user": "u-l1", "roles": ["l1_agent"]}

l2 := {"user": "u-l2", "roles": ["l2_engineer"]}

vendor := {"user": "u-v", "roles": ["vendor_approver"]}

store := {"user": "u-s", "roles": ["store_user"], "store_id": "SW-0001"}

test_it_roles_list if {
	p2_queues.allow with input as {"action": "api.list_tickets", "subject": l1}
	p2_queues.allow with input as {"action": "api.list_tickets", "subject": l2}
	p2_queues.allow with input as {"action": "api.list_tickets", "subject": vendor}
	not p2_queues.allow with input as {"action": "api.list_tickets", "subject": store}
}

test_l1_reads_l1_queue_only if {
	p2_queues.allow with input as {"action": "api.get_ticket", "subject": l1, "resource": {"assignee_queue": "l1", "pending": null}}
	not p2_queues.allow with input as {"action": "api.get_ticket", "subject": l1, "resource": {"assignee_queue": "l2", "pending": null}}
}

test_l2_reads_l2_queue_and_its_pauses if {
	p2_queues.allow with input as {"action": "api.get_ticket", "subject": l2, "resource": {"assignee_queue": "l2", "pending": null}}
	p2_queues.allow with input as {"action": "api.get_ticket", "subject": l2, "resource": {"assignee_queue": "agent", "pending": {"kind": "l2_task"}}}
	p2_queues.allow with input as {"action": "api.get_ticket", "subject": l2, "resource": {"assignee_queue": "agent", "pending": {"kind": "approval", "approver_role": "l2_engineer"}}}
	not p2_queues.allow with input as {"action": "api.get_ticket", "subject": l2, "resource": {"assignee_queue": "store", "pending": {"kind": "store_reply"}}}
	not p2_queues.allow with input as {"action": "api.get_ticket", "subject": l2, "resource": {"assignee_queue": "agent", "pending": {"kind": "approval", "approver_role": "vendor_approver"}}}
}

test_vendor_reads_vendor_approvals_only if {
	p2_queues.allow with input as {"action": "api.get_ticket", "subject": vendor, "resource": {"assignee_queue": "agent", "pending": {"kind": "approval", "approver_role": "vendor_approver"}}}
	not p2_queues.allow with input as {"action": "api.get_ticket", "subject": vendor, "resource": {"assignee_queue": "l2", "pending": null}}
}

test_queues_never_cover_writes if {
	not p2_queues.allow with input as {"action": "api.reply", "subject": l2, "resource": {"assignee_queue": "l2", "pending": null}}
	not p2_queues.allow with input as {"action": "api.create_ticket", "subject": l2, "resource": {}}
}
