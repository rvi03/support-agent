package servewell.p10_default_deny_test

import rego.v1

import data.servewell.p10_default_deny

reader := {"client_id": "agent-reader", "scopes": ["it-data:read", "kb:read"], "aud": ["it-data", "knowledge"]}

test_known_allowed_action if {
	p10_default_deny.allow with input as {"action": "it_data.get_store", "subject": reader}
	p10_default_deny.reason == "allowed" with input as {"action": "it_data.get_store", "subject": reader}
}

test_unlisted_action_denied if {
	not p10_default_deny.allow with input as {"action": "itsm.delete_all_tickets", "subject": reader}
	p10_default_deny.reason == "unknown action" with input as {"action": "itsm.delete_all_tickets", "subject": reader}
}

test_empty_input_denied if {
	not p10_default_deny.allow with input as {}
}

test_known_action_without_policy_allow_denied if {
	not p10_default_deny.allow with input as {"action": "itsm.run_fix", "subject": reader}
	p10_default_deny.reason == "no policy allows" with input as {"action": "itsm.run_fix", "subject": reader}
}

# ---- API routes (S12) ------------------------------------------------------------

store_a := {"client_id": "mock-store-sw-0001", "user": "u-a", "roles": ["store_user"], "store_id": "SW-0001", "scopes": ["api"], "aud": ["api"]}

admin_l2 := {"client_id": "mock-x", "user": "u-x", "roles": ["admin", "l2_engineer"], "store_id": null, "scopes": ["api"], "aud": ["api"]}

card_ticket := {"submitted_by_user": "u-s", "status": "waiting_approval", "kb_rev_current": "kb-1", "sla_passed": false, "pending": {"kind": "approval", "approver_role": "l2_engineer", "kb_rev": "kb-1", "guarded": false}}

test_api_own_store_allowed if {
	p10_default_deny.allow with input as {"action": "api.get_ticket", "subject": store_a, "resource": {"store_id": "SW-0001"}}
}

test_api_other_store_denied if {
	not p10_default_deny.allow with input as {"action": "api.get_ticket", "subject": store_a, "resource": {"store_id": "SW-0002"}}
	p10_default_deny.reason == "no policy allows" with input as {"action": "api.get_ticket", "subject": store_a, "resource": {"store_id": "SW-0002"}}
}

test_api_needs_api_audience_and_scope if {
	no_aud := object.union(store_a, {"aud": ["it-data"]})
	not p10_default_deny.allow with input as {"action": "api.get_ticket", "subject": no_aud, "resource": {"store_id": "SW-0001"}}
	p10_default_deny.reason == "no api token" with input as {"action": "api.get_ticket", "subject": no_aud, "resource": {"store_id": "SW-0001"}}
}

test_api_deny_beats_allow if {
	# P3 would allow the l2_engineer role, but P6 denies any admin approval.
	not p10_default_deny.allow with input as {"action": "api.approve", "subject": admin_l2, "resource": card_ticket}
	p10_default_deny.reason == "admin_cannot_approve" with input as {"action": "api.approve", "subject": admin_l2, "resource": card_ticket}
}

test_api_self_approval_reason if {
	dual := {"client_id": "mock-dual", "user": "u-s", "roles": ["store_user", "l2_engineer"], "store_id": "SW-0001", "scopes": ["api"], "aud": ["api"]}
	not p10_default_deny.allow with input as {"action": "api.approve", "subject": dual, "resource": card_ticket}
	p10_default_deny.reason == "self_approval" with input as {"action": "api.approve", "subject": dual, "resource": card_ticket}
}

test_api_unknown_route_denied if {
	not p10_default_deny.allow with input as {"action": "api.delete_ticket", "subject": store_a}
	p10_default_deny.reason == "unknown action" with input as {"action": "api.delete_ticket", "subject": store_a}
}
