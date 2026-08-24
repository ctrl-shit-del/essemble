"use client";

import { use, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { LanguageFormatModal } from "@/components/booking/LanguageFormatModal";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton, SkeletonText } from "@/components/ui/Skeleton";
import {
  dayKeyOf,
  daysWithShows,
  fetchEvent,
  fetchShowtimes,
  formatLabel,
  languageFormats,
  upcomingDays,
  venuesForDay,
  type LanguageFormat,
} from "@/lib/catalog";
import { formatMoney } from "@/lib/seatmap";
import { describeError } from "@/lib/errors";
import { cn } from "@/lib/cn";

/**
 * Steps 2-5 of the fixed flow, on one progressively-revealed screen:
 * language + format, then date, then venue, then showtime.
 *
 * One screen rather than four routes because the later choices are cheap to
 * change and a customer comparing 6pm at one venue against 7pm at another
 * should not be navigating backwards to do it.
 */
export default function EventPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const eventId = Number(id);
  const router = useRouter();

  const eventQuery = useQuery({
    queryKey: ["event", eventId],
    queryFn: () => fetchEvent(eventId),
    enabled: Number.isInteger(eventId),
  });

  const showtimesQuery = useQuery({
    queryKey: ["showtimes", eventId],
    queryFn: () => fetchShowtimes(eventId),
    enabled: Number.isInteger(eventId),
  });

  const venues = useMemo(() => showtimesQuery.data ?? [], [showtimesQuery.data]);
  const combinations = useMemo(() => languageFormats(venues), [venues]);

  const [combination, setCombination] = useState<LanguageFormat | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [day, setDay] = useState<string | null>(null);

  /**
   * Skip the modal when there is nothing to choose.
   *
   * A single combination is auto-selected and the modal never opens: making
   * someone confirm the only option available is a step that costs a click
   * and teaches nothing.
   */
  useEffect(() => {
    if (combinations.length === 0 || combination) return;
    if (combinations.length === 1) setCombination(combinations[0]);
    else setModalOpen(true);
  }, [combinations, combination]);

  const days = useMemo(() => upcomingDays(7), []);
  const available = useMemo(
    () => daysWithShows(venues, combination),
    [venues, combination],
  );

  // Default to the first day that actually has something.
  useEffect(() => {
    if (day || available.size === 0) return;
    const firstWithShows = days.find((date) => available.has(dayKeyOf(date)));
    if (firstWithShows) setDay(dayKeyOf(firstWithShows));
  }, [day, days, available]);

  const shownVenues = useMemo(
    () => (day ? venuesForDay(venues, day, combination) : []),
    [venues, day, combination],
  );

  if (eventQuery.isLoading || showtimesQuery.isLoading) {
    return <EventSkeleton />;
  }

  if (eventQuery.isError) {
    const { title, detail } = describeError(eventQuery.error, "generic");
    return (
      <EmptyState
        title={title}
        description={detail}
        action={
          <Button onClick={() => router.push("/")}>Back to what&rsquo;s on</Button>
        }
      />
    );
  }

  const event = eventQuery.data!;

  return (
    <div>
      <EventHeader event={event} />

      {combinations.length === 0 ? (
        <EmptyState
          className="mt-10"
          title="No upcoming shows"
          description="Nothing is scheduled for this title yet. Check back soon."
          action={<Button onClick={() => router.push("/")}>See what else is on</Button>}
        />
      ) : (
        <>
          {/* The current choice stays visible and changeable -- someone who
              picked the wrong language should not have to start over. */}
          {combination && combinations.length > 1 && (
            <div className="mt-8 flex flex-wrap items-center gap-3 border-b border-border pb-5">
              <span className="text-[11px] uppercase tracking-[0.14em] text-muted">
                Showing
              </span>
              <Badge tone="accent">
                {combination.language} &middot; {formatLabel(combination.format)}
              </Badge>
              <button
                type="button"
                onClick={() => setModalOpen(true)}
                className="text-[13px] text-muted underline decoration-border underline-offset-4 transition-colors hover:text-text hover:decoration-accent"
              >
                Change
              </button>
            </div>
          )}

          <DateStrip
            days={days}
            selected={day}
            available={available}
            onSelect={setDay}
          />

          <div className="mt-6 space-y-3">
            {shownVenues.length === 0 ? (
              <EmptyState
                title="Nothing on this date"
                description="Try another day in the strip above."
              />
            ) : (
              shownVenues.map((venue) => (
                <Card key={venue.venue_id}>
                  <div className="flex flex-wrap items-baseline justify-between gap-2 p-5 pb-3">
                    <div>
                      <h3 className="font-display text-lg leading-tight text-text">
                        {venue.venue_name}
                      </h3>
                      <p className="mt-0.5 text-[13px] text-muted">
                        {venue.address}
                      </p>
                    </div>
                  </div>

                  <div className="flex flex-wrap gap-2 px-5 pb-5">
                    {venue.shows
                      .slice()
                      .sort(
                        (a, b) =>
                          Date.parse(a.starts_at) - Date.parse(b.starts_at),
                      )
                      .map((show) => (
                        <Link
                          key={show.show_id}
                          href={`/shows/${show.show_id}/seats`}
                          className={cn(
                            "group rounded-lg border border-border bg-surface-2 px-3.5 py-2.5",
                            "transition-colors duration-150 hover:border-accent",
                          )}
                        >
                          <span className="block text-sm text-text tabular-nums">
                            {new Date(show.starts_at).toLocaleTimeString([], {
                              hour: "2-digit",
                              minute: "2-digit",
                            })}
                          </span>
                          <span className="mt-0.5 flex items-baseline gap-2">
                            <span className="text-[11px] text-muted">
                              {show.screen_name}
                            </span>
                            {show.from_price && (
                              <span className="text-[11px] text-muted">
                                from {formatMoney(Number(show.from_price))}
                              </span>
                            )}
                          </span>
                        </Link>
                      ))}
                  </div>
                </Card>
              ))
            )}
          </div>
        </>
      )}

      <LanguageFormatModal
        open={modalOpen}
        options={combinations}
        eventTitle={event.title}
        onSelect={(next) => {
          setCombination(next);
          setModalOpen(false);
          setDay(null); // the new combination may not run on the same days
        }}
        onClose={() => {
          // Closing without choosing must still leave a usable screen.
          if (!combination && combinations.length > 0) setCombination(combinations[0]);
          setModalOpen(false);
        }}
      />
    </div>
  );
}

/* ----------------------------------------------------------------- parts */

function EventHeader({
  event,
}: {
  event: { title: string; description: string | null; genres: string[]; runtime_min: number | null; certification: string | null; artist_name: string | null; event_type: string };
}) {
  return (
    <header>
      <div className="flex flex-wrap items-center gap-2">
        {event.certification && <Badge tone="outline">{event.certification}</Badge>}
        {event.genres.slice(0, 3).map((genre) => (
          <Badge key={genre} tone="neutral">
            {genre}
          </Badge>
        ))}
        {event.runtime_min && (
          <span className="text-[13px] text-muted">
            {Math.floor(event.runtime_min / 60)}h {event.runtime_min % 60}m
          </span>
        )}
      </div>

      <h1 className="mt-3 max-w-3xl font-display text-4xl leading-[1.08] tracking-tight text-text text-balance-title">
        {event.title}
      </h1>

      {event.artist_name && (
        <p className="mt-2 text-[15px] text-accent">{event.artist_name}</p>
      )}
      {event.description && (
        <p className="mt-3 max-w-2xl text-[15px] leading-relaxed text-muted">
          {event.description}
        </p>
      )}
    </header>
  );
}

function DateStrip({
  days,
  selected,
  available,
  onSelect,
}: {
  days: Date[];
  selected: string | null;
  available: Set<string>;
  onSelect: (day: string) => void;
}) {
  return (
    <div className="mt-6">
      <h2 className="text-[11px] uppercase tracking-[0.14em] text-muted">Date</h2>
      <ul className="mt-3 flex gap-2 overflow-x-auto pb-1">
        {days.map((date) => {
          const key = dayKeyOf(date);
          const hasShows = available.has(key);
          const active = selected === key;
          return (
            <li key={key}>
              <button
                type="button"
                onClick={() => hasShows && onSelect(key)}
                disabled={!hasShows}
                aria-pressed={active}
                className={cn(
                  "min-w-[4.25rem] rounded-lg border px-3 py-2.5 text-center transition-colors duration-150",
                  active
                    ? "border-accent bg-accent-soft"
                    : "border-border bg-surface hover:border-border-strong",
                  // Dimmed rather than hidden: the absence of shows on a date
                  // is information, and removing the day would make the strip
                  // shift as the combination changes.
                  !hasShows && "cursor-not-allowed opacity-35 hover:border-border",
                )}
              >
                <span
                  className={cn(
                    "block text-[10px] uppercase tracking-[0.1em]",
                    active ? "text-accent" : "text-muted",
                  )}
                >
                  {date.toLocaleDateString([], { weekday: "short" })}
                </span>
                <span
                  className={cn(
                    "mt-0.5 block font-display text-lg leading-none tabular-nums",
                    active ? "text-accent" : "text-text",
                  )}
                >
                  {date.getDate()}
                </span>
                <span className="mt-0.5 block text-[10px] text-muted">
                  {date.toLocaleDateString([], { month: "short" })}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function EventSkeleton() {
  return (
    <div>
      <Skeleton className="h-5 w-40" />
      <Skeleton className="mt-4 h-11 w-2/3" />
      <SkeletonText className="mt-4 max-w-2xl" lines={2} />
      <div className="mt-8 flex gap-2">
        {Array.from({ length: 7 }).map((_, index) => (
          <Skeleton key={index} className="h-[4.5rem] w-[4.25rem] rounded-lg" />
        ))}
      </div>
      <div className="mt-6 space-y-3">
        {Array.from({ length: 2 }).map((_, index) => (
          <Skeleton key={index} className="h-32 w-full rounded-xl" />
        ))}
      </div>
    </div>
  );
}
