/**
 * Catalogue reads, plus the derivations the booking flow needs from them.
 *
 * The PRD fixes the order: event -> language + format -> date -> venue ->
 * showtime -> seats. Everything below exists to answer one question at each
 * step from a single showtimes payload, rather than asking the API again per
 * step: the combinations, the dates, the venues.
 */

import { api } from "./api";
import {
  eventListItemSchema,
  showDetailSchema,
  venueShowtimesSchema,
  type EventListItem,
  type ShowDetail,
  type ShowFormat,
  type Showtime,
  type VenueShowtimes,
} from "./types";
import { z } from "zod";

export function fetchEvents(): Promise<EventListItem[]> {
  return api.get("/api/events", z.array(eventListItemSchema), { anonymous: true });
}

export function fetchEvent(eventId: number): Promise<EventListItem> {
  return api.get(`/api/events/${eventId}`, eventListItemSchema, { anonymous: true });
}

export function fetchShowtimes(eventId: number): Promise<VenueShowtimes[]> {
  return api.get(
    `/api/events/${eventId}/showtimes`,
    z.array(venueShowtimesSchema),
    { anonymous: true },
  );
}

export function fetchShow(showId: number): Promise<ShowDetail> {
  return api.get(`/api/shows/${showId}`, showDetailSchema, { anonymous: true });
}

/* ------------------------------------------------------- derivations */

export type LanguageFormat = {
  language: string;
  format: ShowFormat | null;
  /** How many upcoming shows carry this combination. */
  count: number;
};

export function flattenShows(venues: VenueShowtimes[]): Showtime[] {
  return venues.flatMap((venue) => venue.shows);
}

/**
 * The combinations that actually have upcoming shows.
 *
 * Derived from the showtimes the API returned, never from a fixed list of
 * languages and formats: offering "Tamil / IMAX" when no such show exists
 * sends someone down a path that dead-ends in an empty screen.
 */
export function languageFormats(venues: VenueShowtimes[]): LanguageFormat[] {
  const counts = new Map<string, LanguageFormat>();
  for (const show of flattenShows(venues)) {
    const key = `${show.language}|${show.format ?? ""}`;
    const existing = counts.get(key);
    if (existing) existing.count += 1;
    else
      counts.set(key, {
        language: show.language,
        format: show.format,
        count: 1,
      });
  }
  return [...counts.values()].sort(
    (a, b) =>
      a.language.localeCompare(b.language) ||
      (a.format ?? "").localeCompare(b.format ?? ""),
  );
}

export function matchesCombination(
  show: Showtime,
  combination: LanguageFormat | null,
): boolean {
  if (!combination) return true;
  return (
    show.language === combination.language && show.format === combination.format
  );
}

/** Local calendar day for a showtime, as YYYY-MM-DD in the viewer's zone. */
export function localDayKey(iso: string): string {
  const date = new Date(iso);
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function dayKeyOf(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

/** The next `count` days from today, in the viewer's own timezone. */
export function upcomingDays(count = 7): Date[] {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Array.from({ length: count }, (_, index) => {
    const date = new Date(today);
    date.setDate(today.getDate() + index);
    return date;
  });
}

/**
 * Venues that have at least one show on `day` matching `combination`, with
 * only those shows attached. Venues with nothing that day drop out entirely
 * rather than rendering as empty cards.
 */
export function venuesForDay(
  venues: VenueShowtimes[],
  day: string,
  combination: LanguageFormat | null,
): VenueShowtimes[] {
  return venues
    .map((venue) => ({
      ...venue,
      shows: venue.shows.filter(
        (show) =>
          localDayKey(show.starts_at) === day &&
          matchesCombination(show, combination),
      ),
    }))
    .filter((venue) => venue.shows.length > 0);
}

/** Days in the strip that have anything to offer, so the rest can be dimmed. */
export function daysWithShows(
  venues: VenueShowtimes[],
  combination: LanguageFormat | null,
): Set<string> {
  const days = new Set<string>();
  for (const show of flattenShows(venues)) {
    if (matchesCombination(show, combination)) {
      days.add(localDayKey(show.starts_at));
    }
  }
  return days;
}

export function formatLabel(format: ShowFormat | null): string {
  if (!format) return "Live";
  return format === "EPIQ_3D" ? "EPIQ 3D" : format;
}
