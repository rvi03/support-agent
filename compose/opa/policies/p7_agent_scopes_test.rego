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

# S6: run-scoped KB exclusions belong to eval-runner only.
evaluator := {"client_id": "eval-runner", "scopes": ["api", "eval:replay", "kb:eval"], "aud": ["api", "knowledge"]}

test_eval_runner_registers_exclusions if {
	p7_agent_scopes.allow with input as {"action": "knowledge.register_exclusions", "subject": evaluator}
	p7_agent_scopes.allow with input as {"action": "knowledge.is_excluded", "subject": evaluator}
}

test_reader_cannot_register_or_see_exclusions if {
	not p7_agent_scopes.allow with input as {"action": "knowledge.register_exclusions", "subject": reader}
	not p7_agent_scopes.allow with input as {"action": "knowledge.is_excluded", "subject": reader}
	with_scope := object.union(reader, {"scopes": ["kb:read", "kb:eval"]})
	not p7_agent_scopes.allow with input as {"action": "knowledge.register_exclusions", "subject": with_scope}
}

test_eval_runner_cannot_search_kb if {
	not p7_agent_scopes.allow with input as {"action": "knowledge.search_kb", "subject": evaluator}
}

test_actor_writes_pending_items if {
	p7_agent_scopes.allow with input as {"action": "itsm.create_pending", "subject": actor}
	p7_agent_scopes.allow with input as {"action": "itsm.clear_pending", "subject": actor}
}

test_reader_cannot_clear_pending if {
	not p7_agent_scopes.allow with input as {"action": "itsm.clear_pending", "subject": reader}
}

test_actor_records_l2_task_results if {
	p7_agent_scopes.allow with input as {"action": "itsm.complete_l2_task", "subject": actor}
	not p7_agent_scopes.allow with input as {"action": "itsm.complete_l2_task", "subject": reader}
}
