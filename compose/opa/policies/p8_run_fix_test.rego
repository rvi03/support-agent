package servewell.p8_run_fix_test

import rego.v1

import data.servewell.p8_run_fix

run := "00000000-0000-4000-8000-000000000001"

base := {
	"subject": {"client_id": "agent-actor"},
	"context": {"run_id": run, "ticket_id": "INC-90001", "store_id": "SW-0001"},
	"request": {"asset_id": "AST-1", "section_id": "runbooks/printer-offline.md#res-1", "quote": "Restart the Windows Print Spooler service", "action_id": "restart_print_spooler", "approval_id": null},
	"now_ns": 1000,
	"ticket_now_ns": 5000,
	"binding": {"id": "po-restart-spooler", "approval": false, "conflict": false},
	"registry": {"version": "reg-1", "action": {"tier": "reversible", "device_families": ["printer", "pos"], "approver": null}},
	"ticket": {"store_id": "SW-0001", "asset_id": "AST-1", "runbook_id": "runbooks/printer-offline.md", "kb_rev": "kb-1", "registry_version": "reg-1", "status": "in_progress", "escalate_by_ns": 9000},
	"asset": {"store_id": "SW-0001", "family": "printer"},
	"section": {"doc_id": "runbooks/printer-offline.md", "kb_rev": "kb-1", "quote_ok": true},
	"autonomy": {"state": "autonomous"},
	"approval": null,
}

good_approval := {
	"run_id": run, "ticket_id": "INC-90001", "asset_id": "AST-1",
	"section_id": "runbooks/printer-offline.md#res-1", "quote": "Restart the Windows Print Spooler service",
	"action_id": "restart_print_spooler", "kb_rev": "kb-1", "decision": "approved",
	"approver_role": "l2_engineer", "expires_ns": 2000, "used": false,
}

supervised := object.union(base, {"autonomy": {"state": "supervised"}})

with_approval(inp, appr) := object.union(inp, {"approval": appr, "request": object.union(inp.request, {"approval_id": "A1"})})

denied(inp, reason) if {
	reason in p8_run_fix.deny with input as inp
	not p8_run_fix.allow with input as inp
}

# ---- runs ------------------------------------------------------------------------

test_autonomous_reversible_runs_alone if {
	p8_run_fix.allow with input as base
}

test_read_only_runs_alone_even_supervised if {
	ro := object.union(supervised, {"registry": {"version": "reg-1", "action": {"tier": "read_only", "device_families": ["printer"], "approver": null}}})
	p8_run_fix.allow with input as ro
}

test_supervised_with_valid_approval_runs if {
	p8_run_fix.allow with input as with_approval(supervised, good_approval)
}

# ---- registry --------------------------------------------------------------------

test_unknown_action if {
	denied(object.union(base, {"registry": {"version": "reg-1", "action": null}}), "unknown_action")
}

test_registry_drift if {
	denied(object.union(base, {"registry": {"version": "reg-2", "action": base.registry.action}}), "registry_drift")
}

# ---- store and asset -------------------------------------------------------------

test_other_store_ticket if {
	denied(object.union(base, {"ticket": object.union(base.ticket, {"store_id": "SW-0002"})}), "other_store")
}

test_ticket_not_found if {
	denied(object.union(base, {"ticket": null}), "ticket_not_found")
}

test_not_ticket_asset if {
	denied(object.union(base, {"request": object.union(base.request, {"asset_id": "AST-2"})}), "not_ticket_asset")
}

test_asset_other_store if {
	denied(object.union(base, {"asset": {"store_id": "SW-0002", "family": "printer"}}), "asset_other_store")
}

# ---- quote binding (S8a) --------------------------------------------------------

test_quote_not_in_section if {
	denied(object.union(base, {"section": object.union(base.section, {"quote_ok": false})}), "quote_not_in_section")
}

test_section_not_in_runbook if {
	denied(object.union(base, {"section": null}), "section_not_in_runbook")
}

test_section_other_runbook if {
	denied(object.union(base, {"section": object.union(base.section, {"doc_id": "runbooks/pos-frozen.md"})}), "section_other_runbook")
}

test_section_other_kb_rev if {
	denied(object.union(base, {"section": object.union(base.section, {"kb_rev": "kb-0"})}), "section_other_kb_rev")
}

test_device_family_excluded if {
	denied(object.union(base, {"asset": {"store_id": "SW-0001", "family": "network"}}), "device_family")
}

# ---- approval --------------------------------------------------------------------

test_supervised_without_approval if {
	denied(supervised, "approval_missing")
}

test_destructive_always_needs_approval if {
	d := object.union(base, {"registry": {"version": "reg-1", "action": {"tier": "destructive", "device_families": ["printer"], "approver": "l2"}}})
	denied(d, "approval_missing")
}

test_expired_approval if {
	denied(with_approval(supervised, object.union(good_approval, {"expires_ns": 1000})), "approval_expired")
}

test_used_approval if {
	denied(with_approval(supervised, object.union(good_approval, {"used": true})), "approval_used")
}

test_rejected_or_undecided_approval if {
	denied(with_approval(supervised, object.union(good_approval, {"decision": "rejected"})), "approval_not_approved")
	denied(with_approval(supervised, object.union(good_approval, {"decision": null})), "approval_not_approved")
}

test_approval_for_other_quote_section_or_kb_rev if {
	denied(with_approval(supervised, object.union(good_approval, {"section_id": "runbooks/printer-offline.md#res-2"})), "approval_binding:section_id")
	denied(with_approval(supervised, object.union(good_approval, {"quote": "Uninstall the printer driver now"})), "approval_binding:quote")
	denied(with_approval(supervised, object.union(good_approval, {"kb_rev": "kb-0"})), "approval_binding:kb_rev")
	denied(with_approval(supervised, object.union(good_approval, {"run_id": "other"})), "approval_binding:run_id")
}

test_vendor_action_needs_vendor_approver if {
	vendor := object.union(supervised, {"registry": {"version": "reg-1", "action": object.union(base.registry.action, {"approver": "vendor"})}})
	denied(with_approval(vendor, good_approval), "approval_role")
	p8_run_fix.allow with input as with_approval(vendor, object.union(good_approval, {"approver_role": "vendor_approver"}))
}

test_unknown_approval_id_refused if {
	inp := object.union(base, {"request": object.union(base.request, {"approval_id": "missing"})})
	denied(inp, "approval_not_found")
}

# ---- fail closed on missing facts ------------------------------------------------

test_missing_section_is_refused if {
	denied(object.remove(base, ["section"]), "section_not_in_runbook")
}

test_missing_ticket_is_refused if {
	denied(object.remove(base, ["ticket"]), "ticket_not_found")
}

test_missing_asset_is_refused if {
	denied(object.remove(base, ["asset"]), "asset_not_found")
}

test_missing_approval_is_refused if {
	denied(object.remove(supervised, ["approval"]), "approval_missing")
}

# ---- S12a: approved binding and ticket state --------------------------------------

test_quote_paired_with_other_action_refused if {
	denied(object.union(base, {"binding": null}), "no_binding")
}

test_missing_binding_fact_refused if {
	denied(object.remove(base, ["binding"]), "no_binding")
}

test_binding_conflict_refused if {
	denied(object.union(base, {"binding": {"id": "x", "approval": false, "conflict": true}}), "binding_conflict")
}

test_runbook_approval_line_needs_approval_even_autonomous if {
	inp := object.union(base, {"binding": {"id": "x", "approval": true, "conflict": false}})
	denied(inp, "approval_missing")
	p8_run_fix.allow with input as with_approval(inp, good_approval)
}

test_closed_ticket_refused if {
	some s in ["resolved", "escalated", "redirected", "closed"]
	denied(object.union(base, {"ticket": object.union(base.ticket, {"status": s})}), "ticket_not_open")
}

test_missing_status_refused if {
	denied(object.union(object.remove(base, ["ticket"]), {"ticket": object.remove(base.ticket, ["status"])}), "ticket_not_open")
}

test_deadline_crossed_after_approval_refused if {
	inp := object.union(supervised, {"ticket_now_ns": 9000})
	denied(with_approval(inp, good_approval), "sla_passed")
}

test_no_deadline_set_runs if {
	p8_run_fix.allow with input as object.union(base, {"ticket": object.union(base.ticket, {"escalate_by_ns": null})})
}

test_missing_ticket_clock_refused if {
	denied(object.remove(base, ["ticket_now_ns"]), "ticket_clock_missing")
}
