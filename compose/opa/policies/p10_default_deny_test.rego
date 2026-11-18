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
