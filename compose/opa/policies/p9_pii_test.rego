package servewell.p9_pii_test

import rego.v1

import data.servewell.p9_pii

test_actor_own_ticket if {
	p9_pii.allow with input as {
		"subject": {"client_id": "agent-actor"},
		"context": {"ticket_id": "INC-90001"},
		"resource": {"ticket_id": "INC-90001"},
	}
}

test_actor_other_ticket_denied if {
	not p9_pii.allow with input as {
		"subject": {"client_id": "agent-actor"},
		"context": {"ticket_id": "INC-90001"},
		"resource": {"ticket_id": "INC-90002"},
	}
}

test_reader_denied if {
	not p9_pii.allow with input as {
		"subject": {"client_id": "agent-reader"},
		"context": {"ticket_id": "INC-90001"},
		"resource": {"ticket_id": "INC-90001"},
	}
}

test_unbound_call_denied if {
	not p9_pii.allow with input as {
		"subject": {"client_id": "agent-actor"},
		"context": {"ticket_id": null},
		"resource": {"ticket_id": null},
	}
	not p9_pii.allow with input as {
		"subject": {"client_id": "agent-actor"},
		"context": {"ticket_id": ""},
		"resource": {"ticket_id": ""},
	}
}
