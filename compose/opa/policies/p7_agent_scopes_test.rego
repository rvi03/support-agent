package servewell.p7_agent_scopes_test

import rego.v1

import data.servewell.p7_agent_scopes

reader := {"client_id": "agent-reader", "scopes": ["it-data:read", "kb:read"], "aud": ["it-data", "knowledge"]}

actor := {"client_id": "agent-actor", "scopes": ["itsm:write", "itsm:run_fix"], "aud": ["itsm-actions"]}

test_reader_reads_it_data if {
	p7_agent_scopes.allow with input as {"action": "it_data.get_asset", "subject": reader}
}

test_reader_searches_kb if {
	p7_agent_scopes.allow with input as {"action": "knowledge.search_kb", "subject": reader}
}

test_reader_cannot_write_itsm if {
	not p7_agent_scopes.allow with input as {"action": "itsm.update_ticket", "subject": reader}
}

test_actor_writes_itsm if {
	p7_agent_scopes.allow with input as {"action": "itsm.message_store", "subject": actor}
}

test_actor_cannot_read_it_data if {
	not p7_agent_scopes.allow with input as {"action": "it_data.get_store", "subject": actor}
}

test_missing_scope_denied if {
	no_scope := object.union(reader, {"scopes": ["kb:read"]})
	not p7_agent_scopes.allow with input as {"action": "it_data.get_store", "subject": no_scope}
}

test_wrong_audience_denied if {
	wrong_aud := object.union(reader, {"aud": ["api"]})
	not p7_agent_scopes.allow with input as {"action": "it_data.get_store", "subject": wrong_aud}
}

# A mock user holding the scope by mistake is still not the owning client.
test_other_client_with_scope_denied if {
	other := object.union(reader, {"client_id": "mock-l2"})
	not p7_agent_scopes.allow with input as {"action": "it_data.get_store", "subject": other}
}
