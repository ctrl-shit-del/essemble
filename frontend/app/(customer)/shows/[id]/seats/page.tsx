"use client";

import { Suspense, use } from "react";
import { useSearchParams } from "next/navigation";
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

  return (
    <Suspense fallback={null}>
      <SeatMapWithPreselection showId={showId} />
    </Suspense>
  );
}

/**
 * `?seats=12,13` pre-SELECTS those seats. It does not hold them.
 *
 * This is how the assistant hands off: it ranked some seats, the customer
 * tapped one of its cards, and they arrive here with that group already
 * highlighted and the Hold button still waiting to be pressed. Selection is
 * client state and always has been -- arriving with one changes nothing
 * about what the server knows.
 */
function SeatMapWithPreselection({ showId }: { showId: number }) {
  const searchParams = useSearchParams();
  const raw = searchParams.get("seats");

  const preselected = raw
    ? raw
        .split(",")
        .map((value) => Number(value.trim()))
        .filter((value) => Number.isInteger(value) && value > 0)
    : [];

  return <SeatMapView showId={showId} preselectedSeatIds={preselected} />;
}
