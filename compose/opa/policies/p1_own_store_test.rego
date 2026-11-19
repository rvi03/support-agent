package servewell.p1_own_store_test

import rego.v1

import data.servewell.p1_own_store

store_a := {"client_id": "mock-store-sw-0001", "user": "u-a", "roles": ["store_user"], "store_id": "SW-0001", "scopes": ["api"], "aud": ["api"]}

runner := {"client_id": "eval-runner", "user": "u-eval", "roles": [], "store_id": null, "scopes": ["api", "eval:replay"], "aud": ["api"]}

test_store_creates_for_own_store if {
	p1_own_store.allow with input as {"action": "api.create_ticket", "subject": store_a, "resource": {"store_id": "SW-0001", "replay": false}}
}

test_store_cannot_create_for_other_store if {
	not p1_own_store.allow with input as {"action": "api.create_ticket", "subject": store_a, "resource": {"store_id": "SW-0002", "replay": false}}
}

test_store_cannot_replay if {
	not p1_own_store.allow with input as {"action": "api.create_ticket", "subject": store_a, "resource": {"store_id": "SW-0001", "replay": true}}
}

test_store_without_store_claim_denied if {
	no_store := object.union(store_a, {"store_id": null})
	not p1_own_store.allow with input as {"action": "api.create_ticket", "subject": no_store, "resource": {"store_id": null}}
}

test_eval_runner_replays if {
	p1_own_store.allow with input as {"action": "api.create_ticket", "subject": runner, "resource": {"store_id": "SW-0003", "replay": true}}
}

test_runner_without_replay_scope_denied if {
	no_scope := object.union(runner, {"scopes": ["api"]})
	not p1_own_store.allow with input as {"action": "api.create_ticket", "subject": no_scope, "resource": {"store_id": "SW-0003", "replay": true}}
}

test_other_client_with_replay_scope_denied if {
	other := object.union(runner, {"client_id": "mock-l2"})
	not p1_own_store.allow with input as {"action": "api.create_ticket", "subject": other, "resource": {"store_id": "SW-0003", "replay": true}}
}

test_store_reads_and_replies_own_store_only if {
	p1_own_store.allow with input as {"action": "api.get_ticket", "subject": store_a, "resource": {"store_id": "SW-0001"}}
	p1_own_store.allow with input as {"action": "api.reply", "subject": store_a, "resource": {"store_id": "SW-0001"}}
	not p1_own_store.allow with input as {"action": "api.get_ticket", "subject": store_a, "resource": {"store_id": "SW-0002"}}
	not p1_own_store.allow with input as {"action": "api.reply", "subject": store_a, "resource": {"store_id": "SW-0002"}}
}

test_runner_reads_only_its_own_tickets if {
	p1_own_store.allow with input as {"action": "api.get_ticket", "subject": runner, "resource": {"store_id": "SW-0003", "submitted_by_user": "u-eval"}}
	not p1_own_store.allow with input as {"action": "api.get_ticket", "subject": runner, "resource": {"store_id": "SW-0003", "submitted_by_user": "u-a"}}
}

test_store_cannot_approve if {
	not p1_own_store.allow with input as {"action": "api.approve", "subject": store_a, "resource": {"store_id": "SW-0001"}}
}
