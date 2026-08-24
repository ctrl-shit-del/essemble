/**
 * Door check-in.
 *
 * The endpoint takes whatever the scanner read -- the QR now encodes a URL,
 * and older tickets carry the bare `reference.signature`. The backend
 * normalises both, so nothing here needs to know which form it has.
 */

import { api, isApiError } from "./api";
import { checkinResponseSchema, type CheckinResponse } from "./types";

export function verifyTicket(qrPayload: string): Promise<CheckinResponse> {
  return api.post("/api/checkin/verify", checkinResponseSchema, {
    qr_payload: qrPayload,
  });
}

/**
 * Three outcomes, and only three. The door needs a decision, not a taxonomy.
 *
 * INVALID deliberately merges a bad signature with someone else's venue.
 * Both mean "do not admit", and telling a stranger holding a forged ticket
 * which of the two it was is free information about how the check works.
 */
export type CheckinOutcome =
  | { kind: "valid"; ticket: CheckinResponse }
  | { kind: "used"; checkedInAt: string | null; reference: string | null }
  | { kind: "invalid"; reference: string | null };

/** Pull the booking reference out of either payload form, for display. */
export function referenceFromPayload(payload: string): string | null {
  const credential = payload.includes("://")
    ? (payload.split("/").pop() ?? "")
    : payload;
  const reference = credential.split(".")[0]?.trim();
  return /^ESB-[A-Z0-9]{6}$/.test(reference ?? "") ? reference : null;
}

export function outcomeFromError(
  error: unknown,
  payload: string,
): CheckinOutcome {
  const reference = referenceFromPayload(payload);

  if (isApiError(error) && error.code === "ALREADY_USED") {
    const details = error.details;
    const checkedInAt =
      details && typeof details === "object" && "checked_in_at" in details
        ? String((details as { checked_in_at: unknown }).checked_in_at)
        : null;
    return { kind: "used", checkedInAt, reference };
  }

  // INVALID_SIGNATURE, FORBIDDEN, NOT_FOUND and anything else all land here.
  return { kind: "invalid", reference };
}
