/** "runbooks/printer-offline.md#l1-resolution" -> "Printer offline · L1 resolution". */
export function sourceLabel(sectionId: string | null | undefined): string | null {
  if (!sectionId) return null;
  const [doc = "", section = ""] = sectionId.split("#");
  const name = (doc.split("/").pop() ?? doc).replace(/\.md$/, "");
  return `${words(name)}${section ? ` · ${words(section)}` : ""}`;
}

function words(slug: string): string {
  const s = slug.replace(/[-_]+/g, " ").trim();
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export function time(iso: string | null | undefined): string {
  if (!iso) return "";
  return new Date(iso).toLocaleString([], { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function slaLeft(minutes: number | null | undefined): string {
  if (minutes === null || minutes === undefined) return "not set";
  if (minutes < 0) return "passed";
  if (minutes < 60) return `${Math.round(minutes)} min left`;
  return `${Math.floor(minutes / 60)} h ${Math.round(minutes % 60)} min left`;
}

export function statusLabel(s: string): string {
  return s.replace(/_/g, " ");
}

/** Who has the ticket right now, in plain words. */
export function holder(t: { pending?: { kind?: string | null } | null; assignee_queue?: string | null; api_status: string; status: string }): string {
  if (t.pending?.kind === "approval") return "IT approval";
  if (t.pending?.kind === "l2_task") return "L2 engineer";
  if (t.pending?.kind === "store_reply" || t.pending?.kind === "answer") return "You (reply needed)";
  if (t.assignee_queue === "l2") return "L2 engineer";
  if (t.assignee_queue === "l1") return "L1 agent";
  if (t.api_status === "running" || t.api_status === "accepted") return "Support agent";
  return statusLabel(t.status);
}

/** A 409 from reply or approve (D53). */
export class Stale extends Error {}

/** Runbook spans keep their markdown; show them as plain text (bold markers dropped). */
export function plain(text: string | null | undefined): string {
  return (text ?? "").replace(/\*\*(.+?)\*\*/g, "$1").replace(/__(.+?)__/g, "$1");
}
