import type { TicketView } from "../api/types";
import { plain, sourceLabel, time } from "../lib/format";

type Item =
  | { type: "store"; text: string; at?: string | null; key: string }
  | { type: "agent"; text: string; kind: string; source: string | null; at?: string | null; key: string }
  | { type: "action"; text: string; at?: string | null; key: string };

/**
 * One timeline: the store's opening subject, the agent's messages, the store's
 * replies and IT actions as grey lines. Replies live only in walk.steps, so the
 * n-th store step's reply goes right after the n-th step message (by turn).
 */
export function buildChat(t: TicketView): Item[] {
  const replies = (t.walk?.steps ?? [])
    .filter((s) => s.kind === "store" && s.outcome === "replied" && s.result)
    .map((s) => s.result as string);
  const timed: Item[] = [];
  let stepNo = 0;
  t.messages.forEach((m, i) => {
    timed.push({ type: "agent", text: plain(m.text), kind: m.kind, source: m.kind === "step" ? sourceLabel(m.section_id) : null, at: m.at, key: `m${i}` });
    if (m.kind === "step") {
      const r = replies[stepNo++];
      if (r) timed.push({ type: "store", text: r, at: null, key: `r${i}` });
    }
  });
  const actions: Item[] = t.actions.map((a, i) => ({
    type: "action",
    text: `IT action ${a.action_id}: ${a.outcome}${a.result ? ` — ${a.result}` : ""}${a.approval_id ? " (approved)" : ""}`,
    at: a.created_at,
    key: `a${i}`,
  }));
  // Merge actions into the message order by time; untimed items keep their place.
  const out: Item[] = [];
  let ai = 0;
  for (const item of timed) {
    while (item.at && ai < actions.length && (actions[ai]?.at ?? "") < item.at) out.push(actions[ai++] as Item);
    out.push(item);
  }
  while (ai < actions.length) out.push(actions[ai++] as Item);
  return out;
}

export function Chat({ t }: { t: TicketView }) {
  const items = buildChat(t);
  return (
    <ol className="chat" aria-label="Conversation" aria-live="polite">
      <li className="bubble store">
        <span className="who-says">You</span>
        <p>{t.subject ?? "New ticket"}</p>
        <span className="meta">{time(t.created_at)}</span>
      </li>
      {items.map((it) =>
        it.type === "action" ? (
          <li key={it.key} className="itline">
            {it.text}
          </li>
        ) : (
          <li key={it.key} className={`bubble ${it.type}`}>
            <span className="who-says">{it.type === "agent" ? "Support agent" : "You"}</span>
            <p>{it.text}</p>
            {it.type === "agent" && it.source && <span className="source">Source: {it.source}</span>}
            {it.at && <span className="meta">{time(it.at)}</span>}
          </li>
        ),
      )}
      {t.api_status === "running" && !t.pending && <li className="typing">Support agent is working…</li>}
    </ol>
  );
}
