# P10 Default deny (D27): the single decision every service asks.
#   POST /v1/data/servewell/p10_default_deny/allow  {"input": {...}}
# An action is allowed only if it is a known action AND a policy for it allows AND
# no policy denies it. Anything unlisted, or listed with no allowing policy, is denied.
#   MCP tools: P7 (P8 and P9 are asked on their own by itsm-actions and the agent).
#   API routes (S12): P1 own store, P2 queues, P3 approve, P4 vendor and L2 tasks, P6 admin.
package servewell.p10_default_deny

import rego.v1

import data.servewell.p1_own_store
import data.servewell.p2_queues
import data.servewell.p3_approve
import data.servewell.p4_vendor_l2
import data.servewell.p6_admin
import data.servewell.p7_agent_scopes

default allow := false

api_actions := {"api.create_ticket", "api.list_tickets", "api.get_ticket", "api.reply", "api.approve"}

# Every action any service may ask about. Unknown names are always denied.
known_actions := p7_agent_scopes.tool_actions | api_actions

# Every API call needs a token for the API audience with the `api` scope.
api_token if {
	"api" in input.subject.aud
	"api" in input.subject.scopes
}

denies := (p3_approve.deny | p4_vendor_l2.deny) | p6_admin.deny

allow if {
	input.action in p7_agent_scopes.tool_actions
	p7_agent_scopes.allow
}

allow if {
	input.action in api_actions
	api_token
	api_allows
	count(denies) == 0
}

api_allows if p1_own_store.allow

api_allows if p2_queues.allow

api_allows if p3_approve.allow

api_allows if p4_vendor_l2.allow

api_allows if p6_admin.allow

reason := "unknown action" if {
	not input.action in known_actions
} else := "allowed" if {
	allow
} else := "no api token" if {
	input.action in api_actions
	not api_token
} else := concat(",", sort([d | some d in denies])) if {
	count(denies) > 0
} else := "no policy allows"
