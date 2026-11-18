# P7 Agent tool scopes (design.md, Agent level): each MCP tool needs one scope,
# and only the service identity that owns that scope may call it.
#   agent-reader: it-data and knowledge reads
#   agent-actor:  itsm writes (run_fix also needs an approval check, P8, S7)
#   eval-runner:  run-scoped KB exclusions for the abstention test (S6)
# Input: {"action": "<server>.<tool>", "subject": {"client_id": ..., "scopes": [...], "aud": [...]}}
package servewell.p7_agent_scopes

import rego.v1

# tool action -> the scope, audience and client it requires
tools := {
	"it_data.get_store": {"scope": "it-data:read", "aud": "it-data", "client": "agent-reader"},
	"it_data.get_asset": {"scope": "it-data:read", "aud": "it-data", "client": "agent-reader"},
	"it_data.get_store_assets": {"scope": "it-data:read", "aud": "it-data", "client": "agent-reader"},
	"it_data.get_sla": {"scope": "it-data:read", "aud": "it-data", "client": "agent-reader"},
	"it_data.get_known_bug": {"scope": "it-data:read", "aud": "it-data", "client": "agent-reader"},
	"it_data.get_ticket": {"scope": "it-data:read", "aud": "it-data", "client": "agent-reader"},
	"it_data.get_recent_tickets": {"scope": "it-data:read", "aud": "it-data", "client": "agent-reader"},
	"knowledge.search_kb": {"scope": "kb:read", "aud": "knowledge", "client": "agent-reader"},
	"knowledge.get_document": {"scope": "kb:read", "aud": "knowledge", "client": "agent-reader"},
	"knowledge.get_runbook_steps": {"scope": "kb:read", "aud": "knowledge", "client": "agent-reader"},
	"knowledge.register_exclusions": {"scope": "kb:eval", "aud": "knowledge", "client": "eval-runner"},
	"knowledge.is_excluded": {"scope": "kb:eval", "aud": "knowledge", "client": "eval-runner"},
	"itsm.update_ticket": {"scope": "itsm:write", "aud": "itsm-actions", "client": "agent-actor"},
	"itsm.post_comment": {"scope": "itsm:write", "aud": "itsm-actions", "client": "agent-actor"},
	"itsm.message_store": {"scope": "itsm:write", "aud": "itsm-actions", "client": "agent-actor"},
	"itsm.escalate": {"scope": "itsm:write", "aud": "itsm-actions", "client": "agent-actor"},
	"itsm.run_fix": {"scope": "itsm:run_fix", "aud": "itsm-actions", "client": "agent-actor"},
}

tool_actions := {name | some name, _ in tools}

default allow := false

allow if {
	rule := tools[input.action]
	input.subject.client_id == rule.client
	rule.scope in input.subject.scopes
	rule.aud in input.subject.aud
}
