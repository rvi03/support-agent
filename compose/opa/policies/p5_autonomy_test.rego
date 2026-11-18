package servewell.p5_autonomy_test

import rego.v1

import data.servewell.p5_autonomy

code := {"kind": "service", "client_id": "itsm-actions", "roles": []}

ready := {"tier": "reversible", "runs_in_a_row": 1, "threshold": 1, "eval_mode": false}

test_code_promotes_reversible_after_threshold if {
	p5_autonomy.allow with input as {"action": "promote", "subject": code, "resource": ready}
}

test_not_before_threshold if {
	early := object.union(ready, {"runs_in_a_row": 2, "threshold": 3})
	not p5_autonomy.allow with input as {"action": "promote", "subject": code, "resource": early}
}

test_never_in_eval_mode if {
	ev := object.union(ready, {"eval_mode": true})
	not p5_autonomy.allow with input as {"action": "promote", "subject": code, "resource": ev}
}

test_destructive_never_promoted if {
	d := object.union(ready, {"tier": "destructive", "runs_in_a_row": 99})
	not p5_autonomy.allow with input as {"action": "promote", "subject": code, "resource": d}
}

test_read_only_never_promoted if {
	r := object.union(ready, {"tier": "read_only"})
	not p5_autonomy.allow with input as {"action": "promote", "subject": code, "resource": r}
}

test_admin_cannot_promote if {
	admin := {"kind": "person", "client_id": "mock-admin", "roles": ["admin"]}
	not p5_autonomy.allow with input as {"action": "promote", "subject": admin, "resource": ready}
}

test_admin_demotes if {
	admin := {"kind": "person", "client_id": "mock-admin", "roles": ["admin"]}
	p5_autonomy.allow with input as {"action": "demote", "subject": admin, "resource": ready}
}

test_l2_cannot_demote_or_promote if {
	l2 := {"kind": "person", "client_id": "mock-l2", "roles": ["l2_engineer"]}
	not p5_autonomy.allow with input as {"action": "demote", "subject": l2, "resource": ready}
	not p5_autonomy.allow with input as {"action": "promote", "subject": l2, "resource": ready}
}

test_person_claiming_service_client_id_cannot_promote if {
	fake := {"kind": "person", "client_id": "itsm-actions", "roles": ["admin"]}
	not p5_autonomy.allow with input as {"action": "promote", "subject": fake, "resource": ready}
}

test_code_demotes if {
	p5_autonomy.allow with input as {"action": "demote", "subject": code, "resource": ready}
}
