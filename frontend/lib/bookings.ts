/**
 * Holds, bookings, waitlist and offers.
 *
 * Thin by design -- each function is one endpoint. The interesting decisions
 * live at the call sites, because what a failure MEANS depends on where the
 * person is standing: a 410 on confirm is "your hold expired during
 * checkout", the same 410 on an offer claim is "someone else got these seats".
 */

import { z } from "zod";
import { api } from "./api";
import {
  bookingSchema,
  cancelResponseSchema,
  confirmResponseSchema,
  holdSchema,
  waitlistEntrySchema,
  waitlistLeaveSchema,
  waitlistOfferSchema,
  type Booking,
  type CancelResponse,
  type ConfirmResponse,
  type Hold,
  type WaitlistEntry,
  type WaitlistOffer,
} from "./types";

/* ----------------------------------------------------------------- holds */

export function fetchHold(holdGroupId: string): Promise<Hold> {
  return api.get(`/api/holds/${holdGroupId}`, holdSchema);
}

/**
 * Confirm a hold into a booking.
 *
 * The Idempotency-Key is attached by lib/api.ts for this exact path. It
 * matters most here: if the response is lost to a timeout, a retry must
 * return the SAME booking rather than attempt a second one, and the caller
 * has no way to tell those apart on its own.
 */
export function confirmHold(
  holdGroupId: string,
  idempotencyKey?: string,
): Promise<ConfirmResponse> {
  return api.post(
    `/api/holds/${holdGroupId}/confirm`,
    confirmResponseSchema,
    undefined,
    { idempotencyKey },
  );
}

/* -------------------------------------------------------------- bookings */

export function fetchBookings(status?: "confirmed" | "cancelled"): Promise<Booking[]> {
  return api.get("/api/bookings", z.array(bookingSchema), {
    query: { status },
  });
}

export function fetchBooking(reference: string): Promise<Booking> {
  return api.get(`/api/bookings/${reference}`, bookingSchema);
}

export function cancelBooking(reference: string): Promise<CancelResponse> {
  return api.post(`/api/bookings/${reference}/cancel`, cancelResponseSchema);
}

/**
 * Upcoming vs past, split on the show's start time rather than on booking
 * status: a cancelled booking for a future show still belongs in history, and
 * a confirmed booking for last week is not something anyone is attending.
 */
export function splitBookings(bookings: Booking[]): {
  upcoming: Booking[];
  past: Booking[];
} {
  const now = Date.now();
  const upcoming: Booking[] = [];
  const past: Booking[] = [];

  for (const booking of bookings) {
    const starts = Date.parse(booking.show.starts_at);
    if (booking.status === "confirmed" && starts > now) upcoming.push(booking);
    else past.push(booking);
  }

  upcoming.sort(
    (a, b) => Date.parse(a.show.starts_at) - Date.parse(b.show.starts_at),
  );
  past.sort(
    (a, b) => Date.parse(b.show.starts_at) - Date.parse(a.show.starts_at),
  );
  return { upcoming, past };
}

/* -------------------------------------------------------------- waitlist */

export function joinWaitlist(
  showId: number,
  categoryId: number,
  qty: number,
): Promise<WaitlistEntry> {
  return api.post("/api/waitlist", waitlistEntrySchema, {
    show_id: showId,
    category_id: categoryId,
    qty,
  });
}

export function fetchWaitlist(): Promise<WaitlistEntry[]> {
  return api.get("/api/waitlist", z.array(waitlistEntrySchema));
}

export function leaveWaitlist(entryId: number) {
  return api.delete(`/api/waitlist/${entryId}`, waitlistLeaveSchema);
}

/* ---------------------------------------------------------------- offers */

/**
 * Read an offer. DELIBERATELY anonymous: the token in the URL is the
 * credential, which is what lets an offer email link straight here without a
 * login wall in front of the information.
 */
export function fetchOffer(token: string): Promise<WaitlistOffer> {
  return api.get(`/api/waitlist/offers/${token}`, waitlistOfferSchema, {
    anonymous: true,
  });
}

/** Claiming, unlike reading, needs the account the offer was made to. */
export function claimOffer(token: string): Promise<ConfirmResponse> {
  return api.post(`/api/waitlist/offers/${token}/claim`, confirmResponseSchema);
}
