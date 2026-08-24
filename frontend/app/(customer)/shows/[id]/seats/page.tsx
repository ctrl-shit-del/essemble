"use client";

import { use } from "react";
import { SeatMapView } from "@/components/seatmap/SeatMapView";
import { EmptyState } from "@/components/ui/EmptyState";

/**
 * Seat selection for one show.
 *
 * Reachable directly at /shows/[id]/seats. Pass 2 builds the map only -- the
 * hold button acquires a real hold and stops there; checkout is the next
 * pass.
 *
 * Deliberately NOT behind RequireRole. Browsing the hall is public, exactly
 * as GET /seatmap is: an evaluator can open the map in two windows without
 * signing in twice to watch the real-time layer work. Only the hold itself
 * needs a session, and the API enforces that.
 */
export default function SeatSelectionPage({
  params,
}: {
  // Next 15 hands params in as a promise.
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const showId = Number(id);

  if (!Number.isInteger(showId) || showId <= 0) {
    return (
      <EmptyState
        title="Invalid show"
        description={`"${id}" is not a show id.`}
      />
    );
  }

  return <SeatMapView showId={showId} />;
}
