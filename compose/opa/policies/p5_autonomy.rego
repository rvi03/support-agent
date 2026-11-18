# P5 Action autonomy (D37, design.md): only code promotes a reversible action to
# autonomous, after the configured number of approved, successful runs in a row,
# and never in eval mode (D47); destructive and read_only actions are never
# promoted. The itsm-actions code and `admin` may demote; nobody promotes by hand.
# Input: {"action": "promote" | "demote",
#         "subject": {"kind": "service" | "person", "client_id": ..., "roles": [...]},
#         "resource": {"tier": ..., "runs_in_a_row": n, "threshold": n, "eval_mode": bool}}
package servewell.p5_autonomy

import rego.v1

code_subject if {
	input.subject.kind == "service"
	input.subject.client_id == "itsm-actions"
}

default allow := false

allow if {
	input.action == "promote"
	code_subject
	input.resource.tier == "reversible"
	input.resource.eval_mode == false
	input.resource.runs_in_a_row >= input.resource.threshold
}

allow if {
	input.action == "demote"
	code_subject
}

allow if {
	input.action == "demote"
	input.subject.kind == "person"
	"admin" in input.subject.roles
}
