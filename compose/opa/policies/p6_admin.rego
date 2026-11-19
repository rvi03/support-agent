# P6 Admin limits (design.md; S12 build step 4): admin reindexes and changes config
# outside the API (D29). Through the API admin may only list and read tickets (the
# masked view, P9); it never creates, replies or approves, whatever other role the
# token also holds. Demotion of an action is P5.
# Input: {"action", "subject": {"roles"}}
package servewell.p6_admin

import rego.v1

admin if "admin" in input.subject.roles

default allow := false

allow if {
	admin
	input.action in {"api.list_tickets", "api.get_ticket"}
}

deny contains "admin_cannot_approve" if {
	admin
	input.action == "api.approve"
}

deny contains "admin_cannot_act_for_a_store" if {
	admin
	input.action in {"api.create_ticket", "api.reply"}
}
