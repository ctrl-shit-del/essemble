/**
 * Seat-map data access and geometry.
 *
 * The geometry half is the part worth reading. The backend's layout generator
 * bakes aisle offsets into each seat's `x`, so a real row looks like:
 *
 *   seat_number  1  2  3  4  5 ... 16 17 18
 *   x            1  2  3  5  6 ... 19 20      <- gaps at 4 and 17
 *
 * Laying out from array position, or from seat_number, silently shifts every
 * seat after the first aisle by one column and the map quietly stops matching
 * the hall. So the renderer works from the stored x/y and nothing else; the
 * aisles then fall out of the coordinates for free, as do missing rows.
 */

import { api } from "./api";
import {
  holdSchema,
  holdReleaseSchema,
  seatMapSchema,
  type Hold,
  type HoldRelease,
  type SeatMap,
  type SeatMapSeat,
  type SeatStatus,
} from "./types";

/** Mirrors the backend's MAX_SEATS_PER_HOLD. */
export const MAX_SEATS_PER_HOLD = 10;

/* ------------------------------------------------------------------ fetch */

/**
 * Fetch the seat map.
 *
 * With `since` set to the last known seat_version the server answers 304 when
 * nothing has moved, and this returns null. That is the normal outcome of a
 * poll tick, not an error.
 */
export async function fetchSeatMap(
  showId: number,
  since?: number,
  signal?: AbortSignal,
): Promise<SeatMap | null> {
  return api.get<SeatMap | null>(
    `/api/shows/${showId}/seatmap`,
    seatMapSchema.nullable(),
    { query: { since }, allowEmpty: true, signal, anonymous: true },
  );
}

export async function createHold(
  showId: number,
  seatIds: number[],
  idempotencyKey?: string,
): Promise<Hold> {
  return api.post<Hold>(
    "/api/holds",
    holdSchema,
    { show_id: showId, seat_ids: seatIds },
    { idempotencyKey },
  );
}

export async function releaseHold(holdGroupId: string): Promise<HoldRelease> {
  return api.delete<HoldRelease>(`/api/holds/${holdGroupId}`, holdReleaseSchema);
}

/* --------------------------------------------------------------- geometry */

export type SeatGeometry = {
  minX: number;
  maxX: number;
  minY: number;
  maxY: number;
  /** Columns spanned INCLUDING aisle gaps, not the seat count per row. */
  columns: number;
  rows: number;
};

export function computeGeometry(seats: SeatMapSeat[]): SeatGeometry {
  if (seats.length === 0) {
    return { minX: 0, maxX: 0, minY: 0, maxY: 0, columns: 0, rows: 0 };
  }
  let minX = Infinity;
  let maxX = -Infinity;
  let minY = Infinity;
  let maxY = -Infinity;

  for (const seat of seats) {
    if (seat.x < minX) minX = seat.x;
    if (seat.x > maxX) maxX = seat.x;
    if (seat.y < minY) minY = seat.y;
    if (seat.y > maxY) maxY = seat.y;
  }

  return {
    minX,
    maxX,
    minY,
    maxY,
    // Spans, computed from the extremes. Deliberately NOT seats-per-row: a
    // row with an aisle spans more columns than it has seats.
    columns: maxX - minX + 1,
    rows: maxY - minY + 1,
  };
}

export type SeatRow = {
  y: number;
  label: string;
  seats: SeatMapSeat[];
};

/**
 * Group seats into rows by their stored y.
 *
 * Rows come back in y order with no attempt to fill gaps: if a hall has no
 * row at y=4 there simply is no entry, and the renderer leaves that band
 * empty rather than shifting everything below it up by one.
 */
export function groupIntoRows(seats: SeatMapSeat[]): SeatRow[] {
  const byY = new Map<number, SeatMapSeat[]>();
  for (const seat of seats) {
    const bucket = byY.get(seat.y);
    if (bucket) bucket.push(seat);
    else byY.set(seat.y, [seat]);
  }

  return [...byY.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([y, rowSeats]) => ({
      y,
      label: rowSeats[0]?.row_label ?? "",
      seats: [...rowSeats].sort((a, b) => a.x - b.x),
    }));
}

/**
 * The y range each category occupies, for the banded labels down the side.
 * Derived from the seats themselves, so a category that does not appear on
 * this screen simply produces no band.
 */
export type CategoryBand = {
  categoryId: number;
  minY: number;
  maxY: number;
};

export function computeCategoryBands(seats: SeatMapSeat[]): CategoryBand[] {
  const bands = new Map<number, CategoryBand>();
  for (const seat of seats) {
    const existing = bands.get(seat.category_id);
    if (!existing) {
      bands.set(seat.category_id, {
        categoryId: seat.category_id,
        minY: seat.y,
        maxY: seat.y,
      });
    } else {
      if (seat.y < existing.minY) existing.minY = seat.y;
      if (seat.y > existing.maxY) existing.maxY = seat.y;
    }
  }
  return [...bands.values()].sort((a, b) => a.minY - b.minY);
}

/* ----------------------------------------------------------------- pricing */

export function priceOf(map: SeatMap, categoryId: number): number {
  const category = map.categories.find((item) => item.id === categoryId);
  return category ? Number(category.price) : 0;
}

export function categoryName(map: SeatMap, categoryId: number): string {
  return map.categories.find((item) => item.id === categoryId)?.name ?? "";
}

/**
 * "A4". Takes the minimum a label needs rather than a full SeatMapSeat, so
 * the same function labels a held seat, a booked seat and a map seat -- three
 * different API shapes that all carry a row and a number.
 */
export function seatLabel(seat: {
  row_label: string;
  seat_number: number;
}): string {
  return `${seat.row_label}${seat.seat_number}`;
}

/** Rupees, grouped Indian-style, no decimals when whole. */
export function formatMoney(amount: number): string {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: amount % 1 === 0 ? 0 : 2,
  }).format(amount);
}

/* ----------------------------------------------------------------- patching */

/**
 * Apply a status change to named seats, returning a NEW seats array and the
 * ids that actually moved.
 *
 * Reporting what changed is what drives the transition animation: only seats
 * whose status genuinely differed should flash, or a redundant event repaints
 * half the map for no reason.
 */
export function patchSeatStatuses(
  seats: SeatMapSeat[],
  seatIds: number[],
  status: SeatStatus,
): { seats: SeatMapSeat[]; changed: number[] } {
  const target = new Set(seatIds);
  const changed: number[] = [];

  const next = seats.map((seat) => {
    if (!target.has(seat.seat_id) || seat.status === status) return seat;
    changed.push(seat.seat_id);
    return { ...seat, status };
  });

  return changed.length > 0 ? { seats: next, changed } : { seats, changed };
}

/**
 * Diff two full maps, for the poll path. The poll returns everything, so the
 * only way to know what to animate is to compare against what we had.
 */
export function diffSeatStatuses(
  previous: SeatMapSeat[],
  next: SeatMapSeat[],
): number[] {
  const before = new Map(previous.map((seat) => [seat.seat_id, seat.status]));
  const changed: number[] = [];
  for (const seat of next) {
    const was = before.get(seat.seat_id);
    if (was !== undefined && was !== seat.status) changed.push(seat.seat_id);
  }
  return changed;
}
