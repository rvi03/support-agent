package servewell.p4_vendor_l2_test

import rego.v1

import data.servewell.p4_vendor_l2

l2 := {"user": "u-l2", "roles": ["l2_engineer"]}

vendor := {"user": "u-v", "roles": ["vendor_approver"]}

vcard := {"kind": "approval", "approver_role": "vendor_approver", "kb_rev": "kb-1", "guarded": false}

base := {"submitted_by_user": "u-store", "status": "waiting_approval", "kb_rev_current": "kb-1", "sla_passed": false}

test_vendor_approves_vendor_card if {
	p4_vendor_l2.allow with input as {"action": "api.approve", "subject": vendor, "resource": object.union(base, {"pending": vcard})}
}

test_l2_cannot_approve_vendor_card if {
	r := object.union(base, {"pending": vcard})
	not p4_vendor_l2.allow with input as {"action": "api.approve", "subject": l2, "resource": r}
	"wrong_approver_role" in p4_vendor_l2.deny with input as {"action": "api.approve", "subject": l2, "resource": r}
}

test_l2_task_only_by_l2_engineer if {
	r := object.union(base, {"status": "waiting_l2", "pending": {"kind": "l2_task"}})
	p4_vendor_l2.allow with input as {"action": "api.approve", "subject": l2, "resource": r}
	not p4_vendor_l2.allow with input as {"action": "api.approve", "subject": vendor, "resource": r}
	"l2_task_needs_l2_engineer" in p4_vendor_l2.deny with input as {"action": "api.approve", "subject": vendor, "resource": r}
}

test_guarded_step_never_approvable if {
	guarded := object.union(vcard, {"guarded": true})
	r := object.union(base, {"pending": guarded})
	not p4_vendor_l2.allow with input as {"action": "api.approve", "subject": vendor, "resource": r}
	"guarded_never_approvable" in p4_vendor_l2.deny with input as {"action": "api.approve", "subject": vendor, "resource": r}
}

test_vendor_requester_cannot_approve if {
	r := object.union(base, {"submitted_by_user": "u-v", "pending": vcard})
	not p4_vendor_l2.allow with input as {"action": "api.approve", "subject": vendor, "resource": r}
}
