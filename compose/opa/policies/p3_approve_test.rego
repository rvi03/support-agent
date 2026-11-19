package servewell.p3_approve_test

import rego.v1

import data.servewell.p3_approve

l2 := {"user": "u-l2", "roles": ["l2_engineer"]}

dual := {"user": "u-dual", "roles": ["store_user", "l2_engineer"]}

card := {"kind": "approval", "approver_role": "l2_engineer", "kb_rev": "kb-1", "guarded": false}

open_ticket := {"submitted_by_user": "u-store", "status": "waiting_approval", "kb_rev_current": "kb-1", "sla_passed": false, "pending": card}

test_l2_approves_an_open_card if {
	p3_approve.allow with input as {"action": "api.approve", "subject": l2, "resource": open_ticket}
	count(p3_approve.deny) == 0 with input as {"action": "api.approve", "subject": l2, "resource": open_ticket}
}

test_requester_cannot_approve if {
	mine := object.union(open_ticket, {"submitted_by_user": "u-dual"})
	not p3_approve.allow with input as {"action": "api.approve", "subject": dual, "resource": mine}
	p3_approve.deny == {"self_approval"} with input as {"action": "api.approve", "subject": dual, "resource": mine}
}

test_requester_denied_even_with_nothing_pending if {
	mine := object.union(open_ticket, {"submitted_by_user": "u-dual", "pending": null})
	not p3_approve.allow with input as {"action": "api.approve", "subject": dual, "resource": mine}
}

test_nothing_pending_passes_through_to_409 if {
	none_open := object.union(open_ticket, {"pending": null, "status": "resolved"})
	p3_approve.allow with input as {"action": "api.approve", "subject": l2, "resource": none_open}
}

test_closed_ticket_denied if {
	closed := object.union(open_ticket, {"status": "resolved"})
	not p3_approve.allow with input as {"action": "api.approve", "subject": l2, "resource": closed}
	"ticket_closed" in p3_approve.deny with input as {"action": "api.approve", "subject": l2, "resource": closed}
}

test_changed_kb_rev_denied if {
	moved := object.union(open_ticket, {"kb_rev_current": "kb-2"})
	not p3_approve.allow with input as {"action": "api.approve", "subject": l2, "resource": moved}
	"kb_rev_changed" in p3_approve.deny with input as {"action": "api.approve", "subject": l2, "resource": moved}
}

test_sla_passed_denied if {
	late := object.union(open_ticket, {"sla_passed": true})
	not p3_approve.allow with input as {"action": "api.approve", "subject": l2, "resource": late}
	"sla_passed" in p3_approve.deny with input as {"action": "api.approve", "subject": l2, "resource": late}
}

test_missing_sla_fact_denied if {
	no_sla := object.remove(open_ticket, ["sla_passed"])
	not p3_approve.allow with input as {"action": "api.approve", "subject": l2, "resource": no_sla}
}

test_store_user_is_not_an_approver if {
	store := {"user": "u-s", "roles": ["store_user"]}
	not p3_approve.allow with input as {"action": "api.approve", "subject": store, "resource": open_ticket}
	"not_an_approver" in p3_approve.deny with input as {"action": "api.approve", "subject": store, "resource": open_ticket}
}

test_vendor_card_is_not_p3 if {
	vcard := object.union(open_ticket, {"pending": object.union(card, {"approver_role": "vendor_approver"})})
	not p3_approve.allow with input as {"action": "api.approve", "subject": l2, "resource": vcard}
}

test_no_deny_for_other_actions if {
	count(p3_approve.deny) == 0 with input as {"action": "api.get_ticket", "subject": dual, "resource": object.union(open_ticket, {"submitted_by_user": "u-dual"})}
}
