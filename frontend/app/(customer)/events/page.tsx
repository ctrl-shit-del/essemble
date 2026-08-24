"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Badge } from "@/components/ui/Badge";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { fetchEvents } from "@/lib/catalog";
import { describeError } from "@/lib/errors";
import { formatMoney } from "@/lib/seatmap";

/**
 * The entry point to the booking flow.
 *
 * Deliberately modest: this pass is about the path from an event to a
 * confirmed booking, and a designed browse experience is a separate concern.
 * What it does have to get right is not offering anything unbookable -- a
 * title with no upcoming shows leads to a dead end, so it says so on the card
 * rather than letting someone find out a screen later.
 */
export default function EventsPage() {
  const query = useQuery({ queryKey: ["events"], queryFn: fetchEvents });

  if (query.isLoading) {
    return (
      <div>
        <Skeleton className="h-9 w-48" />
        <div className="mt-8 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, index) => (
            <Skeleton key={index} className="h-40 w-full rounded-xl" />
          ))}
        </div>
      </div>
    );
  }

  if (query.isError) {
    const { title, detail } = describeError(query.error);
    return <EmptyState title={title} description={detail} />;
  }

  const events = query.data ?? [];

  return (
    <div>
      <h1 className="font-display text-3xl leading-tight tracking-tight text-text">
        What&rsquo;s on
      </h1>
      <p className="mt-1.5 text-[15px] text-muted">
        Films and live events with seats available now.
      </p>

      {events.length === 0 ? (
        <EmptyState
          className="mt-8"
          title="Nothing scheduled"
          description="No events have upcoming shows yet."
        />
      ) : (
        <ul className="mt-8 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {events.map((event) => {
            const bookable = event.upcoming_shows > 0;
            return (
              <li key={event.id}>
                <Card interactive className="h-full">
                  <Link
                    href={`/events/${event.id}`}
                    className="flex h-full flex-col p-5"
                  >
                    <div className="flex flex-wrap items-center gap-1.5">
                      {event.certification && (
                        <Badge tone="outline">{event.certification}</Badge>
                      )}
                      {event.genres.slice(0, 2).map((genre) => (
                        <Badge key={genre} tone="neutral">
                          {genre}
                        </Badge>
                      ))}
                    </div>

                    <h2 className="mt-3 font-display text-lg leading-tight text-text">
                      {event.title}
                    </h2>
                    {event.artist_name && (
                      <p className="mt-0.5 text-[13px] text-accent">
                        {event.artist_name}
                      </p>
                    )}

                    <p className="mt-auto pt-4 text-[13px] text-muted">
                      {bookable ? (
                        <>
                          {event.upcoming_shows}{" "}
                          {event.upcoming_shows === 1 ? "show" : "shows"}
                          {event.from_price && (
                            <> &middot; from {formatMoney(Number(event.from_price))}</>
                          )}
                        </>
                      ) : (
                        "No upcoming shows"
                      )}
                    </p>
                  </Link>
                </Card>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
