import type { TicketItem } from "../api/types";
import { holder, slaLeft, statusLabel, time } from "../lib/format";

export function StatusBar({ t }: { t: TicketItem }) {
  const acting = t.pending?.kind === "approval" || t.pending?.kind === "l2_task";
  return (
    <dl className="statusbar" aria-label="Ticket status">
      <div><dt>Status</dt><dd>{statusLabel(t.status)}</dd></div>
      <div><dt>Priority</dt><dd>{t.priority ?? "—"}</dd></div>
      <div><dt>Asset</dt><dd>{t.asset_id ?? "—"}</dd></div>
      <div><dt>Escalate by</dt><dd>{t.escalate_by ? `${time(t.escalate_by)} (${slaLeft(t.sla_minutes_left)})` : "—"}</dd></div>
      <div><dt>With</dt><dd className={acting ? "act" : undefined}>{holder(t)}</dd></div>
    </dl>
  );
}
