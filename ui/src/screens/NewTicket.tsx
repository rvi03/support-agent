import { useEffect, useRef, useState } from "react";
import { useAuth } from "../auth/AuthProvider";
import { createTicket } from "../api/calls";

const URGENCY = [
  { value: "P4", label: "Low: it can wait" },
  { value: "P3", label: "Normal: slows us down" },
  { value: "P2", label: "High: hurts sales now" },
  { value: "P1", label: "Critical: we cannot trade" },
];

export function NewTicket({ onCreated, onCancel }: { onCreated: (id: string) => void; onCancel: () => void }) {
  const { api } = useAuth();
  const [subject, setSubject] = useState("");
  const [description, setDescription] = useState("");
  const [device, setDevice] = useState("");
  const [urgency, setUrgency] = useState("P3");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const first = useRef<HTMLInputElement>(null);
  useEffect(() => first.current?.focus(), []);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const id = await createTicket(api, {
        subject: subject.trim(),
        description: description.trim(),
        priority: urgency,
        ...(device.trim() ? { asset_id: device.trim().toUpperCase() } : {}),
      });
      onCreated(id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not create the ticket.");
      setBusy(false);
    }
  };

  return (
    <form
      className="newticket"
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
    >
      <div className="ticket-head">
        <button type="button" className="btn ghost back" onClick={onCancel}>← Tickets</button>
        <h2>New ticket</h2>
      </div>
      <p className="muted">Your name and phone come from your sign-in, so you don't need to type them.</p>
      <label>
        Subject
        <input ref={first} required maxLength={200} value={subject} onChange={(e) => setSubject(e.target.value)} placeholder="e.g. Receipt printer shows Offline" />
      </label>
      <label>
        What is happening?
        <textarea required rows={5} maxLength={4000} value={description} onChange={(e) => setDescription(e.target.value)} placeholder="What you see, since when, and what you already tried." />
      </label>
      <label>
        Device id <span className="muted">(optional)</span>
        <input value={device} maxLength={40} onChange={(e) => setDevice(e.target.value)} placeholder="e.g. PRN-0012-01" aria-describedby="device-hint" />
        <span id="device-hint" className="hint">It's on the label on the device.</span>
      </label>
      <fieldset>
        <legend>Urgency</legend>
        <div className="radios">
          {URGENCY.map((u) => (
            <label key={u.value} className="radio">
              <input type="radio" name="urgency" value={u.value} checked={urgency === u.value} onChange={() => setUrgency(u.value)} />
              {u.label}
            </label>
          ))}
        </div>
      </fieldset>
      {error && <p role="alert" className="notice">Could not create the ticket: {error}</p>}
      <div className="actions">
        <button type="button" className="btn ghost" onClick={onCancel}>Cancel</button>
        <button className="btn primary" type="submit" disabled={busy || !subject.trim() || !description.trim()}>
          {busy ? "Sending…" : "Create ticket"}
        </button>
      </div>
    </form>
  );
}
