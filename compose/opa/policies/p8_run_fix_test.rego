package servewell.p8_run_fix_test

import rego.v1

import data.servewell.p8_run_fix

run := "00000000-0000-4000-8000-000000000001"

base := {
	"subject": {"client_id": "agent-actor"},
	"context": {"run_id": run, "ticket_id": "INC-90001", "store_id": "SW-0001"},
	"request": {"asset_id": "AST-1", "step_id": "res.usb.1", "action_id": "restart_print_spooler", "approval_id": null},
	"now_ns": 1000,
	"registry": {"version": "reg-1", "action": {"tier": "reversible", "device_families": ["printer", "pos"], "approver": null}},
	"ticket": {"store_id": "SW-0001", "asset_id": "AST-1", "runbook_id": "runbooks/printer-offline.md", "kb_rev": "kb-1", "registry_version": "reg-1"},
	"asset": {"store_id": "SW-0001", "family": "printer"},
	"step": {"doc_id": "runbooks/printer-offline.md", "kb_rev": "kb-1", "action_id": "restart_print_spooler", "team": "it", "flags": [], "approver": null},
	"autonomy": {"state": "autonomous"},
	"approval": null,
}

good_approval := {
	"run_id": run, "ticket_id": "INC-90001", "asset_id": "AST-1", "step_id": "res.usb.1",
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

# ---- step binding (M4) -----------------------------------------------------------

test_step_maps_to_other_action if {
	denied(object.union(base, {"step": object.union(base.step, {"action_id": "clear_print_queue"})}), "step_other_action")
}

test_step_other_runbook if {
	denied(object.union(base, {"step": object.union(base.step, {"doc_id": "runbooks/pos-frozen.md"})}), "step_other_runbook")
}

test_step_other_kb_rev if {
	denied(object.union(base, {"step": object.union(base.step, {"kb_rev": "kb-0"})}), "step_other_kb_rev")
}

test_step_missing if {
	denied(object.union(base, {"step": null}), "step_not_found")
}

test_store_step_is_not_run if {
	denied(object.union(base, {"step": object.union(base.step, {"team": "store"})}), "step_not_it")
}

test_device_family_excluded if {
	denied(object.union(base, {"asset": {"store_id": "SW-0001", "family": "network"}}), "device_family")
}

# ---- prohibitions before approval (D51) ------------------------------------------

test_guarded_step_refused_with_valid_approval if {
	guarded := object.union(supervised, {"step": object.union(base.step, {"flags": ["guard"]})})
	denied(with_approval(guarded, good_approval), "prohibited_step:guard")
}

test_l2_only_secret_conflict_refused if {
	every f in ["l2_only", "secret", "conflict"] {
		denied(object.union(base, {"step": object.union(base.step, {"flags": [f]})}), sprintf("prohibited_step:%s", [f]))
	}
}

# ---- approval --------------------------------------------------------------------

test_supervised_without_approval if {
	denied(supervised, "approval_missing")
}

test_destructive_always_needs_approval if {
	d := object.union(base, {"registry": {"version": "reg-1", "action": {"tier": "destructive", "device_families": ["printer"], "approver": "l2"}}})
	denied(d, "approval_missing")
}

test_approval_tag_forces_approval_on_autonomous if {
	tagged := object.union(base, {"step": object.union(base.step, {"flags": ["approval"]})})
	denied(tagged, "approval_missing")
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

test_approval_for_other_step_or_kb_rev if {
	denied(with_approval(supervised, object.union(good_approval, {"step_id": "res.usb.2"})), "approval_binding:step_id")
	denied(with_approval(supervised, object.union(good_approval, {"kb_rev": "kb-0"})), "approval_binding:kb_rev")
	denied(with_approval(supervised, object.union(good_approval, {"run_id": "other"})), "approval_binding:run_id")
}

test_vendor_step_needs_vendor_approver if {
	vendor := object.union(supervised, {"step": object.union(base.step, {"approver": "vendor"})})
	denied(with_approval(vendor, good_approval), "approval_role")
	p8_run_fix.allow with input as with_approval(vendor, object.union(good_approval, {"approver_role": "vendor_approver"}))
}

test_unknown_approval_id_refused if {
	inp := object.union(base, {"request": object.union(base.request, {"approval_id": "missing"})})
	denied(inp, "approval_not_found")
}
