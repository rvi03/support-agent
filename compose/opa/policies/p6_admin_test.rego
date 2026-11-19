package servewell.p6_admin_test

import rego.v1

import data.servewell.p6_admin

admin := {"user": "u-admin", "roles": ["admin"]}

test_admin_reads if {
	p6_admin.allow with input as {"action": "api.list_tickets", "subject": admin}
	p6_admin.allow with input as {"action": "api.get_ticket", "subject": admin}
}

test_admin_never_approves_replies_or_creates if {
	"admin_cannot_approve" in p6_admin.deny with input as {"action": "api.approve", "subject": admin}
	"admin_cannot_act_for_a_store" in p6_admin.deny with input as {"action": "api.reply", "subject": admin}
	"admin_cannot_act_for_a_store" in p6_admin.deny with input as {"action": "api.create_ticket", "subject": admin}
	not p6_admin.allow with input as {"action": "api.approve", "subject": admin}
}

test_no_deny_without_admin if {
	count(p6_admin.deny) == 0 with input as {"action": "api.approve", "subject": {"roles": ["l2_engineer"]}}
}
