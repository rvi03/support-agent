import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "../auth/AuthProvider";
import { getTicket, listTickets, reply } from "../api/calls";
import type { TicketItem } from "../api/types";
import { usePoll } from "../lib/usePoll";
import { Stale, statusLabel, time } from "../lib/format";
import { Chat } from "../components/Chat";
import { StatusBar } from "../components/StatusBar";
import { NewTicket } from "./NewTicket";

export function StoreHome() {
  const { api } = useAuth();
  const [open, setOpen] = useState<string | "new" | null>(null);
  const list = usePoll(() => listTickets(api), "store-list");
  const tickets = list.data ?? [];

  return (
    <div className={`split ${open ? "has-detail" : ""}`}>
      <aside className="pane list-pane" aria-label="My tickets">
        <div className="pane-head">
          <h2>My tickets</h2>
          <button className="btn primary" onClick={() => setOpen("new")}>New ticket</button>
        </div>
        {list.data && tickets.length === 0 && <p className="muted pad">No tickets yet.</p>}
        <ul className="ticket-list">
          {tickets.map((t) => (
            <li key={t.ticket_id}>
              <TicketRow t={t} active={open === t.ticket_id} onOpen={() => setOpen(t.ticket_id)} />
            </li>
          ))}
        </ul>
      </aside>
      <section className="pane detail-pane">
        {open === "new" ? (
          <NewTicket
            onCancel={() => setOpen(null)}
            onCreated={(id) => {
              setOpen(id);
              void list.refresh();
            }}
          />
        ) : open ? (
          <TicketChat id={open} onBack={() => setOpen(null)} />
        ) : (
          <p className="empty muted">Pick a ticket or raise a new one.</p>
        )}
      </section>
    </div>
  );
}

function TicketRow({ t, active, onOpen }: { t: TicketItem; active: boolean; onOpen: () => void }) {
  const needsYou = t.pending?.kind === "store_reply" || t.pending?.kind === "answer";
  return (
    <button className={`ticket-row ${active ? "active" : ""}`} aria-current={active || undefined} onClick={onOpen}>
      <span className="row-top">
        <span className="tid">{t.ticket_id}</span>
        {needsYou ? <span className="pill act">Reply needed</span> : <span className="pill">{statusLabel(t.status)}</span>}
      </span>
      <span className="row-subject">{t.subject ?? "Processing…"}</span>
      <span className="meta">{time(t.created_at)}</span>
    </button>
  );
}

function TicketChat({ id, onBack }: { id: string; onBack: () => void }) {
  const { api } = useAuth();
  const load = useCallback(() => getTicket(api, id), [api, id]);
  const view = usePoll(load, `ticket-${id}`);
  const t = view.data;
  const headRef = useRef<HTMLHeadingElement>(null);
  const boxRef = useRef<HTMLTextAreaElement>(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => headRef.current?.focus(), [id]);

  const canReply = !!t?.pending && (t.pending.kind === "store_reply" || t.pending.kind === "answer");
  const send = async () => {
    if (!t?.pending || !text.trim()) return;
    setBusy(true);
    setNotice(null);
    try {
      await reply(api, id, t.pending.pending_id, text.trim());
      setText("");
    } catch (e) {
      if (e instanceof Stale) {
        setNotice("This was already handled. The ticket has been refreshed.");
        headRef.current?.focus();
      } else setNotice(e instanceof Error ? `Could not send: ${e.message}` : "Could not send.");
    } finally {
      setBusy(false);
      await view.refresh();
    }
  };

  if (!t) return <p className="empty muted">{view.error ? `Could not load: ${view.error}` : "Loading…"}</p>;
  return (
    <div className="ticket">
      <div className="ticket-head">
        <button className="btn ghost back" onClick={onBack}>← Tickets</button>
        <h2 tabIndex={-1} ref={headRef}>{t.subject ?? t.ticket_id}</h2>
        <span className="meta">{t.ticket_id}</span>
      </div>
      <StatusBar t={t} />
      {notice && <p role="status" className="notice">{notice}</p>}
      <Chat t={t} />
      <form
        className="replybox"
        onSubmit={(e) => {
          e.preventDefault();
          void send();
        }}
      >
        <label htmlFor="reply" className="sr-only">Your reply</label>
        <textarea
          id="reply"
          ref={boxRef}
          rows={2}
          value={text}
          disabled={!canReply || busy}
          placeholder={canReply ? "Tell us what you see…" : "You can reply when the agent asks you something."}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) void send();
          }}
        />
        <button className="btn primary" type="submit" disabled={!canReply || busy || !text.trim()}>
          Send
        </button>
      </form>
    </div>
  );
}
