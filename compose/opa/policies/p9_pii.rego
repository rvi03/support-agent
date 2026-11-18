# P9 PII (design.md, D5): only agent-actor (the reply sender) handles real contact
# values, and only for the ticket the call is bound to. itsm-actions asks it for
# every store message; the agent asks it before reading pii.vault (S10).
# Input: {"subject": {"client_id": ...},
#         "context": {"ticket_id": <the call's bound ticket>},
#         "resource": {"ticket_id": <the ticket whose contact is used>}}
package servewell.p9_pii

import rego.v1

default allow := false

allow if {
	input.subject.client_id == "agent-actor"
	is_string(input.context.ticket_id)
	input.context.ticket_id != ""
	input.resource.ticket_id == input.context.ticket_id
}
