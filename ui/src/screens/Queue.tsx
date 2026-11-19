import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "../auth/AuthProvider";
import { decide, getTicket, listTickets, type Decision } from "../api/calls";
import type { ApprovalCard, TicketItem, TicketView } from "../api/types";
import { usePoll } from "../lib/usePoll";
import { Stale, plain, slaLeft, sourceLabel, statusLabel, time } from "../lib/format";

/** IT · approval queue (S13 step 5): needs approval + handed to L2, role-filtered. */
export function Queue() {
  const { api, who } = useAuth();
  const list = usePoll(() => listTickets(api), "queue");
  const [open, setOpen] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const rowRefs = useRef(new Map<string, HTMLButtonElement>());

  const mine = (t: TicketItem) => !!t.pending?.approver_role && who.roles.includes(t.pending.approver_role as never);
  const all = list.data ?? [];
  const approvals = all.filter((t) => t.pending?.kind === "approval" && mine(t));
  const isL2 = who.roles.includes("l2_engineer");
  const l2 = isL2 ? all.filter((t) => t.pending?.kind === "l2_task" || (!t.pending && t.assignee_queue === "l2")) : [];

  /** After a decision: focus the next item that needs someone, else the queue heading. */
  const afterDecision = async (msg: string | null) => {
    setNotice(msg);
    await list.refresh();
    setOpen(null);
  };
  const headRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    if (open !== null) return;
    const next = [...approvals, ...l2.filter((t) => t.pending)][0];
    const el = next ? rowRefs.current.get(next.ticket_id) : null;
    if (notice !== null) (el ?? headRef.current)?.focus();
  }, [open, notice]);

  return (
    <div className={`split ${open ? "has-detail" : ""}`}>
      <aside className="pane list-pane" aria-label="Queues">
        <div className="pane-head"><h2 tabIndex={-1} ref={headRef}>Queue</h2></div>
        {notice && <p role="status" className="notice">{notice}</p>}
        <QueueList title="Needs approval" items={approvals} open={open} onOpen={setOpen} refs={rowRefs.current} empty="Nothing waits for your approval." />
        {isL2 && <QueueList title="Handed to L2" items={l2} open={open} onOpen={setOpen} refs={rowRefs.current} empty="No L2 tasks or handoffs." />}
      </aside>
      <section className="pane detail-pane">
        {open ? (
          <Card key={open} id={open} onBack={() => setOpen(null)} onDone={afterDecision} />
        ) : (
          <p className="empty muted">Pick an item to review.</p>
        )}
      </section>
    </div>
  );
}

function QueueList(props: {
  title: string;
  items: TicketItem[];
  open: string | null;
  onOpen: (id: string) => void;
  refs: Map<string, HTMLButtonElement>;
  empty: string;
}) {
  const id = props.title.toLowerCase().replace(/\W+/g, "-");
  return (
    <section aria-labelledby={id} className="qsection">
      <h3 id={id}>
        {props.title} <span className="count">{props.items.length}</span>
      </h3>
      {props.items.length === 0 && <p className="muted pad">{props.empty}</p>}
      <ul className="ticket-list">
        {props.items.map((t) => (
          <li key={t.ticket_id}>
            <button
              ref={(el) => {
                if (el) props.refs.set(t.ticket_id, el);
                else props.refs.delete(t.ticket_id);
              }}
              className={`ticket-row ${props.open === t.ticket_id ? "active" : ""}`}
              aria-current={props.open === t.ticket_id || undefined}
              onClick={() => props.onOpen(t.ticket_id)}
            >
              <span className="row-top">
                <span className="tid">{t.store_id} · {t.ticket_id}</span>
                {t.pending ? (
                  <span className="pill act">{t.pending.kind === "approval" ? "Approve?" : "L2 task"}</span>
                ) : (
                  <span className="pill">{statusLabel(t.status)}</span>
                )}
              </span>
              <span className="row-subject">{t.subject ?? "—"}</span>
              <span className="meta">{t.priority ?? "—"} · SLA {slaLeft(t.sla_minutes_left)}</span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

function Card({ id, onBack, onDone }: { id: string; onBack: () => void; onDone: (msg: string | null) => Promise<void> }) {
  const { api } = useAuth();
  const load = useCallback(() => getTicket(api, id), [api, id]);
  const view = usePoll(load, `card-${id}`);
  const t = view.data;
  const headRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => headRef.current?.focus(), [id]);

  if (!t) return <p className="empty muted">{view.error ? `Could not load: ${view.error}` : "Loading…"}</p>;
  const p = t.pending;
  return (
    <article className="card" aria-labelledby="card-title">
      <div className="ticket-head">
        <button className="btn ghost back" onClick={onBack}>← Queue</button>
        <h2 id="card-title" tabIndex={-1} ref={headRef}>{t.subject ?? t.ticket_id}</h2>
        <span className="meta">{t.ticket_id}</span>
      </div>
      <dl className="facts">
        <div><dt>Store</dt><dd>{t.store_id}</dd></div>
        <div><dt>Asset</dt><dd>{p?.approval?.asset_id ?? t.asset_id ?? "—"}</dd></div>
        <div><dt>Priority</dt><dd>{t.priority ?? "—"}</dd></div>
        <div><dt>SLA</dt><dd>{slaLeft(t.sla_minutes_left)}</dd></div>
        {p?.approval && <div><dt>Warranty</dt><dd>{warranty(p.approval)}</dd></div>}
      </dl>
      {p?.kind === "approval" ? (
        <ApprovalBody t={t} onDone={onDone} />
      ) : p?.kind === "l2_task" ? (
        <TaskBody t={t} onDone={onDone} />
      ) : t.assignee_queue !== "l2" ? (
        <section className="block">
          <h3>Nothing waits here now</h3>
          <p>This item was already handled. Status: {statusLabel(t.status)}.</p>
        </section>
      ) : (
        <section className="block">
          <h3>Handed to L2</h3>
          <p>
            {t.outcome?.handoff_reason ? `Reason: ${statusLabel(t.outcome.handoff_reason)}.` : "Handed off."} The handoff note is on the ticket.
          </p>
        </section>
      )}
    </article>
  );
}

function ApprovalBody({ t, onDone }: { t: TicketView; onDone: (msg: string | null) => Promise<void> }) {
  const card = t.pending?.approval;
  const source = sourceLabel(card?.section_id);
  return (
    <>
      <section className="block">
        <h3>Step to approve</h3>
        <p className="step">{card?.step ?? t.pending?.step_id}</p>
        <dl className="facts">
          <div><dt>Action</dt><dd><code>{card?.action_id ?? "—"}</code></dd></div>
          <div><dt>Does</dt><dd>{card?.action ?? "—"}</dd></div>
          <div><dt>Tier</dt><dd>{card?.tier ?? "—"}</dd></div>
          <div><dt>Autonomy</dt><dd>{autonomy(card)}</dd></div>
        </dl>
      </section>
      {card?.quote && (
        <section className="block">
          <h3>Runbook says</h3>
          <blockquote>{plain(card.quote)}</blockquote>
          {source && <p className="source">Source: {source}</p>}
        </section>
      )}
      <p className="muted small">Reject hands the ticket to L2 with your reason, and the action goes back to supervised.</p>
      <Decide t={t} onDone={onDone} yes="approve" no="reject" yesLabel="Approve" noLabel="Reject" needText="no" textLabel="Reason (required to reject)" />
    </>
  );
}

function TaskBody({ t, onDone }: { t: TicketView; onDone: (msg: string | null) => Promise<void> }) {
  const task = [...(t.l2_tasks ?? [])].reverse().find((x) => !x.result) ?? null;
  const source = sourceLabel(task?.section_id);
  return (
    <>
      <section className="block">
        <h3>L2 task</h3>
        {task?.reason && <p><strong>Why L2:</strong> {statusLabel(task.reason)}</p>}
        {task?.note && <blockquote className="pre">{plain(task.note)}</blockquote>}
        {source && <p className="source">Source: {source}</p>}
      </section>
      <Decide t={t} onDone={onDone} yes="done" no="failed" yesLabel="Done" noLabel="Failed" needText="both" textLabel="Result (what you did and saw)" />
    </>
  );
}

function Decide(props: {
  t: TicketView;
  onDone: (msg: string | null) => Promise<void>;
  yes: Decision;
  no: Decision;
  yesLabel: string;
  noLabel: string;
  needText: "no" | "both";
  textLabel: string;
}) {
  const { api } = useAuth();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pendingId = props.t.pending?.pending_id;

  const go = async (decision: Decision) => {
    const needs = props.needText === "both" || decision === props.no;
    if (needs && !text.trim()) {
      setError(decision === props.no && props.needText === "no" ? "A reason is required to reject." : "Please write the result.");
      return;
    }
    if (!pendingId) return;
    setBusy(true);
    setError(null);
    try {
      await decide(api, props.t.ticket_id, pendingId, decision, text.trim() || undefined);
      await props.onDone(`${props.t.ticket_id}: ${decision === "approve" ? "approved" : decision === "reject" ? "rejected" : `marked ${decision}`}.`);
    } catch (e) {
      if (e instanceof Stale) await props.onDone("This was already handled. The queue has been refreshed.");
      else {
        setError(e instanceof Error ? e.message : "Failed.");
        setBusy(false);
      }
    }
  };

  return (
    <div className="decide">
      <label>
        {props.textLabel}
        <textarea rows={2} value={text} onChange={(e) => setText(e.target.value)} maxLength={1000} />
      </label>
      {error && <p role="alert" className="notice">{error}</p>}
      <div className="actions">
        <button className="btn danger" disabled={busy} onClick={() => void go(props.no)}>{props.noLabel}</button>
        <button className="btn act" disabled={busy} onClick={() => void go(props.yes)}>{props.yesLabel}</button>
      </div>
    </div>
  );
}

/** "supervised, 0 of 1" (design.md approval card). */
function autonomy(c: ApprovalCard | null | undefined): string {
  if (!c?.autonomy_state) return "—";
  return c.runs_needed != null ? `${c.autonomy_state}, ${c.runs_in_a_row ?? 0} of ${c.runs_needed}` : c.autonomy_state;
}

function warranty(c: ApprovalCard): string {
  if (c.in_warranty == null) return "unknown";
  const until = c.warranty_expiry ? ` (until ${time(c.warranty_expiry).split(",")[0]})` : "";
  return c.in_warranty ? `in warranty${until}` : `out of warranty${until}`;
}
