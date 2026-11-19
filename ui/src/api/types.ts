// Response shapes, generated from docs/openapi.json (`make ui-types`): TicketList,
// TicketView and their parts. Keys only some callers get (l2_tasks, approvals, notes,
// audit for IT roles; outcome and walk once the graph ran) are optional.
import type { components } from "./schema";

type S = components["schemas"];
export type TicketItem = S["TicketItem"];
export type TicketView = S["TicketView"];
export type Pending = S["Pending"];
export type ApprovalCard = S["ApprovalCard"];
export type Message = S["Message"];
export type ActionRow = S["ActionRow"];
export type L2Task = S["L2TaskRow"];

export interface ApiErrorBody {
  error: string;
  status: number;
}
