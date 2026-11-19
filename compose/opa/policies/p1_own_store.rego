# P1 Own store (design.md, Authorization policies; S12): a store user acts only on
# tickets of the store in their token; the body never names a store. The eval
# runner alone replays dataset tickets (scope eval:replay, D52), acting for the
# source ticket's store, and reads or replies only on tickets it submitted.
# Input: {"action": "api.<route>",
#         "subject": {"client_id", "user", "roles", "store_id", "scopes", "aud"},
#         "resource": {"store_id", "submitted_by_user", "replay", ...}}
package servewell.p1_own_store

import rego.v1

store_actions := {"api.create_ticket", "api.list_tickets", "api.get_ticket", "api.reply"}

default allow := false

store_user if {
	"store_user" in input.subject.roles
	is_string(input.subject.store_id)
	input.subject.store_id != ""
}

eval_runner if {
	input.subject.client_id == "eval-runner"
	"eval:replay" in input.subject.scopes
}

own_store if {
	store_user
	input.resource.store_id == input.subject.store_id
}

# Ordinary intake: the store comes from the token (the API sets resource.store_id).
allow if {
	input.action == "api.create_ticket"
	object.get(input.resource, "replay", false) == false
	own_store
}

# Replay of a dataset ticket (D52): eval-runner only.
allow if {
	input.action == "api.create_ticket"
	input.resource.replay == true
	eval_runner
	is_string(input.resource.store_id)
}

allow if {
	input.action == "api.list_tickets"
	store_user
}

allow if {
	input.action == "api.list_tickets"
	eval_runner
}

allow if {
	input.action in {"api.get_ticket", "api.reply"}
	own_store
}

allow if {
	input.action in {"api.get_ticket", "api.reply"}
	eval_runner
	is_string(input.resource.submitted_by_user)
	input.resource.submitted_by_user == input.subject.user
}
