# P10 Default deny (D27): the single decision every service asks.
#   POST /v1/data/servewell/p10_default_deny/allow  {"input": {...}}
# An action is allowed only if it is a known action AND a policy for it allows.
# Anything unlisted, or listed with no allowing policy, is denied.
# Later sub-tasks add P1-P6, P8 and P9 and list them in `policy_allows`.
package servewell.p10_default_deny

import rego.v1

import data.servewell.p7_agent_scopes

default allow := false

# Every action any service may ask about. Unknown names are always denied.
known_actions := p7_agent_scopes.tool_actions

allow if {
	input.action in known_actions
	policy_allows
}

policy_allows if p7_agent_scopes.allow

reason := "unknown action" if {
	not input.action in known_actions
} else := "no policy allows" if {
	not allow
} else := "allowed"
