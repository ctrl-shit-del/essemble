/**
 * Types for the ESSEMBLE API, written against the OpenAPI schema at /docs.
 *
 * Every response the UI branches on is validated with zod rather than cast.
 * The reason is specific to this backend: the booking engine derives seat
 * status at read time and expiry is authoritative via timestamps, so a shape
 * change there is a correctness bug that would otherwise surface as a blank
 * seat map rather than an error. Validating at the boundary makes it loud.
 *
 * The error codes below are the backend's ErrorCode enum. They are the thing
 * callers switch on -- never the HTTP status, which is deliberately reused
 * (409 covers both SEAT_UNAVAILABLE and HOLD_LIMIT_EXCEEDED).
 */

import { z } from "zod";

/* ---------------------------------------------------------------- errors */

export const ERROR_CODES = [
  "SEAT_UNAVAILABLE",
  "HOLD_EXPIRED",
  "HOLD_LIMIT_EXCEEDED",
  "OFFER_EXPIRED",
  "INVALID_SIGNATURE",
  "ALREADY_USED",
  "NOT_SOLD_OUT",
  "FORBIDDEN",
  "VALIDATION_ERROR",
  "UNAUTHENTICATED",
  "NOT_FOUND",
  "CONFLICT",
  "INTERNAL_ERROR",
] as const;

export type ErrorCode = (typeof ERROR_CODES)[number];

/** Codes the client invents for failures that never reached the server. */
export type TransportErrorCode = "NETWORK_ERROR" | "TIMEOUT" | "MALFORMED_RESPONSE";

export type AnyErrorCode = ErrorCode | TransportErrorCode;

export const errorEnvelopeSchema = z.object({
  error: z.object({
    code: z.string(),
    message: z.string(),
    details: z.unknown().nullable().optional(),
  }),
});

/** Field-level detail carried by VALIDATION_ERROR. */
export const validationDetailSchema = z.array(
  z.object({ field: z.string(), message: z.string() }),
);

/** `details` on SEAT_UNAVAILABLE: exactly which seats were lost. */
export const seatUnavailableDetailSchema = z.object({
  seat_ids: z.array(z.number()),
});

/* ------------------------------------------------------------------ auth */

export const userRoleSchema = z.enum(["customer", "organiser", "admin"]);
export type UserRole = z.infer<typeof userRoleSchema>;

export const userSchema = z.object({
  id: z.number(),
  email: z.string(),
  name: z.string(),
  role: userRoleSchema,
  phone: z.string().nullable().optional(),
  created_at: z.string(),
});
export type User = z.infer<typeof userSchema>;

export const tokenResponseSchema = z.object({
  access_token: z.string(),
  token_type: z.string(),
  expires_in: z.number(),
  user: userSchema,
});
export type TokenResponse = z.infer<typeof tokenResponseSchema>;

/* --------------------------------------------------------------- catalog */

export const showFormatSchema = z.enum(["2D", "3D", "IMAX", "EPIQ_3D"]);
export type ShowFormat = z.infer<typeof showFormatSchema>;

export const eventTypeSchema = z.enum(["movie", "live"]);
export type EventType = z.infer<typeof eventTypeSchema>;

export const showStatusSchema = z.enum(["scheduled", "cancelled", "completed"]);

export const eventSchema = z.object({
  id: z.number(),
  organiser_id: z.number(),
  event_type: eventTypeSchema,
  title: z.string(),
  description: z.string().nullable(),
  poster_url: z.string().nullable(),
  backdrop_url: z.string().nullable(),
  runtime_min: z.number().nullable(),
  certification: z.string().nullable(),
  genres: z.array(z.string()),
  release_date: z.string().nullable(),
  tmdb_id: z.number().nullable(),
  artist_name: z.string().nullable(),
  created_at: z.string(),
});
export type Event = z.infer<typeof eventSchema>;

export const eventListItemSchema = eventSchema.extend({
  upcoming_shows: z.number(),
  next_show_at: z.string().nullable(),
  cities: z.array(z.string()),
  from_price: z.string().nullable(),
});
export type EventListItem = z.infer<typeof eventListItemSchema>;

export const showSchema = z.object({
  id: z.number(),
  event_id: z.number(),
  screen_id: z.number(),
  organiser_id: z.number(),
  starts_at: z.string(),
  language: z.string(),
  format: showFormatSchema.nullable(),
  status: showStatusSchema,
  seat_version: z.number(),
  created_at: z.string(),
});
export type Show = z.infer<typeof showSchema>;

/** The compact show shape embedded in hold/booking responses. */
export const bookingShowSummarySchema = z.object({
  show_id: z.number(),
  event_title: z.string(),
  venue_name: z.string(),
  screen_name: z.string(),
  starts_at: z.string(),
  language: z.string(),
  format: showFormatSchema.nullable(),
});
export type BookingShowSummary = z.infer<typeof bookingShowSummarySchema>;

/* -------------------------------------------------------------- seat map */

/**
 * Derived at read time from seat_claim -- never stored, never cached
 * server-side. `available` includes a hold whose expires_at has passed but
 * which the sweeper has not yet collected.
 */
export const seatStatusSchema = z.enum(["available", "held", "booked"]);
export type SeatStatus = z.infer<typeof seatStatusSchema>;

export const seatMapSeatSchema = z.object({
  seat_id: z.number(),
  row_label: z.string(),
  seat_number: z.number(),
  /** Already aisle-adjusted by the backend; render it directly. */
  x: z.number(),
  y: z.number(),
  category_id: z.number(),
  status: seatStatusSchema,
});
export type SeatMapSeat = z.infer<typeof seatMapSeatSchema>;

export const seatMapCategorySchema = z.object({
  id: z.number(),
  name: z.string(),
  rank: z.number(),
  price: z.string(),
});
export type SeatMapCategory = z.infer<typeof seatMapCategorySchema>;

export const seatMapSchema = z.object({
  show_id: z.number(),
  /**
   * Monotonic. Poll with ?since=<seat_version> for a 304 when nothing has
   * moved; the SSE stream carries the same number, so the two paths can be
   * reconciled without a refetch.
   */
  seat_version: z.number(),
  event_title: z.string(),
  venue_name: z.string(),
  screen_name: z.string(),
  starts_at: z.string(),
  language: z.string(),
  format: showFormatSchema.nullable(),
  rows: z.number(),
  columns: z.number(),
  categories: z.array(seatMapCategorySchema),
  seats: z.array(seatMapSeatSchema),
});
export type SeatMap = z.infer<typeof seatMapSchema>;

/** One frame from GET /api/shows/{id}/seatmap/stream. */
export const seatChangeEventSchema = z.object({
  show_id: z.number(),
  seat_ids: z.array(z.number()),
  status: seatStatusSchema,
  seat_version: z.number(),
});
export type SeatChangeEvent = z.infer<typeof seatChangeEventSchema>;

/* ----------------------------------------------------------------- holds */

export const heldSeatSchema = z.object({
  seat_id: z.number(),
  row_label: z.string(),
  seat_number: z.number(),
  category_id: z.number(),
  category_name: z.string(),
  price: z.string(),
});
export type HeldSeat = z.infer<typeof heldSeatSchema>;

export const holdSchema = z.object({
  hold_group_id: z.string(),
  show_id: z.number(),
  /**
   * The authority on when this hold dies. `seconds_remaining` is a
   * convenience computed by the server at response time and is stale the
   * instant it arrives -- always count down from expires_at.
   */
  expires_at: z.string(),
  seconds_remaining: z.number(),
  seats: z.array(heldSeatSchema),
  total: z.string(),
});
export type Hold = z.infer<typeof holdSchema>;

export const holdReleaseSchema = z.object({
  hold_group_id: z.string(),
  released_seat_ids: z.array(z.number()),
  /** Releasing twice is not an error; this distinguishes the two outcomes. */
  already_released: z.boolean(),
});
export type HoldRelease = z.infer<typeof holdReleaseSchema>;

/* -------------------------------------------------------------- bookings */

export const bookingStatusSchema = z.enum(["confirmed", "cancelled"]);
export type BookingStatus = z.infer<typeof bookingStatusSchema>;

export const confirmResponseSchema = z.object({
  reference: z.string(),
  status: z.string(),
  show: bookingShowSummarySchema,
  seats: z.array(heldSeatSchema),
  total: z.string(),
  qr_signature: z.string(),
  created_at: z.string(),
});
export type ConfirmResponse = z.infer<typeof confirmResponseSchema>;

export const bookingSchema = z.object({
  reference: z.string(),
  status: bookingStatusSchema,
  show: bookingShowSummarySchema,
  seats: z.array(heldSeatSchema),
  total: z.string(),
  qr_signature: z.string().nullable(),
  checked_in_at: z.string().nullable(),
  cancelled_at: z.string().nullable(),
  created_at: z.string(),
});
export type Booking = z.infer<typeof bookingSchema>;

export const cancelledOfferSchema = z.object({
  offer_id: z.number(),
  entry_id: z.number(),
  seat_ids: z.array(z.number()),
  seat_labels: z.array(z.string()),
  category_name: z.string(),
  expires_at: z.string(),
});

export const cancelResponseSchema = z.object({
  reference: z.string(),
  status: z.string(),
  cancelled_at: z.string().nullable(),
  refund_amount: z.string(),
  offers_created: z.array(cancelledOfferSchema),
});
export type CancelResponse = z.infer<typeof cancelResponseSchema>;

/* -------------------------------------------------------------- waitlist */

export const waitlistEntryStateSchema = z.enum([
  "waiting",
  "offered",
  "converted",
  "declined",
  "cancelled",
]);
export type WaitlistEntryState = z.infer<typeof waitlistEntryStateSchema>;

export const waitlistEntrySchema = z.object({
  id: z.number(),
  show: bookingShowSummarySchema,
  category_id: z.number(),
  category_name: z.string(),
  qty: z.number(),
  state: waitlistEntryStateSchema,
  /** Computed at read time, never stored. Null unless state is 'waiting'. */
  position: z.number().nullable(),
  created_at: z.string(),
  offer_expires_at: z.string().nullable(),
  offer_seconds_remaining: z.number().nullable(),
});
export type WaitlistEntry = z.infer<typeof waitlistEntrySchema>;

export const waitlistLeaveSchema = z.object({
  id: z.number(),
  state: waitlistEntryStateSchema,
});

/**
 * A time-limited claim on freed seats. Read unauthenticated -- the token in
 * the URL is the credential, and an expired, already-claimed or unknown token
 * all answer OFFER_EXPIRED identically so the token space cannot be probed.
 */
export const waitlistOfferSchema = z.object({
  show: bookingShowSummarySchema,
  category_name: z.string(),
  seats: z.array(heldSeatSchema),
  total: z.string(),
  expires_at: z.string(),
  seconds_remaining: z.number(),
});
export type WaitlistOffer = z.infer<typeof waitlistOfferSchema>;

/* ---------------------------------------------------------------- system */

export const workerHealthSchema = z.object({
  enabled: z.boolean(),
  interval_seconds: z.number(),
  last_run_at: z.string().nullable(),
});

export const healthSchema = z.object({
  status: z.enum(["ok", "degraded"]),
  environment: z.string(),
  database: z.enum(["up", "down"]),
  migration_revision: z.string().nullable(),
  sweeper: workerHealthSchema,
  outbox: workerHealthSchema,
  pending_outbox: z.number().nullable(),
  realtime_connected: z.boolean(),
});
export type Health = z.infer<typeof healthSchema>;

/* ------------------------------------------------------------- showtimes */

/** One bookable showtime, as returned inside a venue grouping. */
export const showtimeSchema = z.object({
  show_id: z.number(),
  starts_at: z.string(),
  language: z.string(),
  format: showFormatSchema.nullable(),
  venue_id: z.number(),
  venue_name: z.string(),
  city: z.string(),
  screen_id: z.number(),
  screen_name: z.string(),
  /** Cheapest category on this show. Null if the show has no pricing. */
  from_price: z.string().nullable(),
});
export type Showtime = z.infer<typeof showtimeSchema>;

export const venueShowtimesSchema = z.object({
  venue_id: z.number(),
  venue_name: z.string(),
  city: z.string(),
  address: z.string(),
  shows: z.array(showtimeSchema),
});
export type VenueShowtimes = z.infer<typeof venueShowtimesSchema>;

export const showDetailSchema = showSchema.extend({
  event: eventSchema,
  venue_id: z.number(),
  venue_name: z.string(),
  city: z.string(),
  screen_name: z.string(),
  total_seats: z.number(),
  pricing: z.array(seatMapCategorySchema),
});
export type ShowDetail = z.infer<typeof showDetailSchema>;

/* --------------------------------------------------------------- checkin */

export const checkinResponseSchema = z.object({
  result: z.string(),
  reference: z.string(),
  event_title: z.string(),
  venue_name: z.string(),
  screen_name: z.string(),
  starts_at: z.string(),
  customer_name: z.string(),
  seats: z.array(z.string()),
  checked_in_at: z.string(),
});
export type CheckinResponse = z.infer<typeof checkinResponseSchema>;
