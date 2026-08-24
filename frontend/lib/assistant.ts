/**
 * The assistant's client half.
 *
 * The conversation lives here, in the client, and is sent with every request.
 * The server keeps nothing -- no session, no transcript table, nothing to
 * expire or leak.
 */

import { z } from "zod";
import { api } from "./api";

export const showOptionSchema = z.object({
  kind: z.literal("show"),
  show_id: z.number(),
  title: z.string(),
  venue: z.string(),
  city: z.string().nullable().optional(),
  screen: z.string(),
  starts_at: z.string(),
  language: z.string(),
  format: z.string().nullable().optional(),
  from_price: z.string().nullable().optional(),
  seats_available: z.number(),
});
export type ShowOption = z.infer<typeof showOptionSchema>;

export const seatOptionSchema = z.object({
  kind: z.literal("seats"),
  show_id: z.number(),
  seat_ids: z.array(z.number()),
  seats: z.array(z.string()),
  row: z.string(),
  category: z.string(),
  category_id: z.number(),
  price_per_seat: z.string(),
  total: z.string(),
  reason: z.string(),
  score_breakdown: z.record(z.string(), z.unknown()),
});
export type SeatOption = z.infer<typeof seatOptionSchema>;

export const assistantOptionSchema = z.discriminatedUnion("kind", [
  showOptionSchema,
  seatOptionSchema,
]);
export type AssistantOption = z.infer<typeof assistantOptionSchema>;

export const chatResponseSchema = z.object({
  reply: z.string(),
  options: z.array(assistantOptionSchema),
  tool_calls_made: z.array(z.string()),
});
export type ChatResponse = z.infer<typeof chatResponseSchema>;

export type ChatTurn = { role: "user" | "assistant"; content: string };

/** One message in the transcript, with whatever it produced attached. */
export type ChatMessage = ChatTurn & {
  id: string;
  options?: AssistantOption[];
  tools?: string[];
};

export function sendMessage(
  message: string,
  conversation: ChatTurn[],
): Promise<ChatResponse> {
  return api.post("/api/assistant/chat", chatResponseSchema, {
    message,
    conversation,
  });
}

/** Human names for the tools, for the "what just happened" line. */
const TOOL_LABELS: Record<string, string> = {
  find_shows: "searched shows",
  get_show_availability: "checked availability",
  rank_seats: "ranked seats",
  get_user_context: "read your booking history",
};

export function describeTools(tools: string[]): string {
  const seen = [...new Set(tools)];
  return seen.map((tool) => TOOL_LABELS[tool] ?? tool).join(" · ");
}

/* ------------------------------------------------------------ persistence */

const STORAGE_KEY = "essemble.assistant";

/**
 * sessionStorage, NOT localStorage.
 *
 * A conversation should survive navigating between pages in this tab and
 * nothing more. localStorage would leave someone's booking questions sitting
 * on a shared machine indefinitely, which is not a trade a ticket site needs
 * to make for a convenience this small.
 */
export function loadConversation(): ChatMessage[] {
  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as ChatMessage[]) : [];
  } catch {
    return [];
  }
}

export function saveConversation(messages: ChatMessage[]): void {
  try {
    window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(messages));
  } catch {
    // Private mode, or full. The conversation still works for this page.
  }
}

export function clearConversation(): void {
  try {
    window.sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // Nothing to clear.
  }
}

export const EXAMPLE_PROMPTS = [
  "Two seats tonight, somewhere close",
  "Cheapest good seats under ₹600",
  "What's on this weekend?",
];
