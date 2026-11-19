import type { Api } from "./client";
import type { ApiErrorBody, TicketItem, TicketView } from "./types";
import { Stale } from "../lib/format";

function fail(status: number, body: unknown): never {
  const reason = (body as ApiErrorBody | undefined)?.error ?? `HTTP ${status}`;
  if (status === 409) throw new Stale(reason);
  throw new Error(reason);
}

export async function listTickets(api: Api): Promise<TicketItem[]> {
  const { data, error, response } = await api.GET("/tickets");
  if (!response.ok) fail(response.status, error);
  return data?.tickets ?? [];
}

export async function getTicket(api: Api, id: string): Promise<TicketView> {
  const { data, error, response } = await api.GET("/tickets/{ticket_id}", { params: { path: { ticket_id: id } } });
  if (!response.ok) fail(response.status, error);
  return data as TicketView;
}

export interface NewTicketInput {
  subject: string;
  description: string;
  asset_id?: string;
  priority?: string;
}

export async function createTicket(api: Api, body: NewTicketInput): Promise<string> {
  const { data, error, response } = await api.POST("/tickets", { body });
  if (!response.ok) fail(response.status, error);
  return (data as { ticket_id: string }).ticket_id;
}

export async function reply(api: Api, id: string, pending_id: string, text: string): Promise<void> {
  const { error, response } = await api.POST("/tickets/{ticket_id}/reply", {
    params: { path: { ticket_id: id } },
    body: { pending_id, text },
  });
  if (!response.ok) fail(response.status, error);
}

export type Decision = "approve" | "reject" | "done" | "failed";

export async function decide(
  api: Api,
  id: string,
  pending_id: string,
  decision: Decision,
  text: string | undefined,
): Promise<void> {
  const isTask = decision === "done" || decision === "failed";
  const { error, response } = await api.POST("/tickets/{ticket_id}/approve", {
    params: { path: { ticket_id: id } },
    body: { pending_id, decision, ...(isTask ? { result: text } : { reason: text }) },
  });
  // Once decided, the ticket may leave this approver's queue, and the API answers 404
  // for a ticket the caller can no longer see (D132): for a decision that is "handled".
  if (response.status === 404) throw new Stale("no_longer_in_your_queue");
  if (!response.ok) fail(response.status, error);
}
