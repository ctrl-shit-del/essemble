"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { SeatMapCanvas } from "./SeatMapCanvas";
import { SeatMapSkeleton } from "./SeatMapSkeleton";
import { SelectionBar } from "./SelectionBar";
import { ConnectionIndicator } from "./ConnectionIndicator";
import { WaitlistPanel } from "./WaitlistPanel";
import { useLiveSeatMap } from "@/hooks/useLiveSeatMap";
import { useToast } from "@/components/ui/Toast";
import { EmptyState } from "@/components/ui/EmptyState";
import { Button } from "@/components/ui/Button";
import { SeatLegend } from "@/components/ui/SeatPattern";
import { isApiError } from "@/lib/api";
import { describeError } from "@/lib/errors";
import { MAX_SEATS_PER_HOLD, createHold, seatLabel } from "@/lib/seatmap";
import type { SeatMapSeat } from "@/lib/types";

export function SeatMapView({
  showId,
  preselectedSeatIds = [],
}: {
  showId: number;
  /** From the assistant hand-off. A selection, never a hold. */
  preselectedSeatIds?: number[];
}) {
  const live = useLiveSeatMap(showId);
  const toast = useToast();
  const router = useRouter();

  /**
   * THE SELECTION IS CLIENT-SIDE ONLY.
   *
   * It lives here and nowhere else -- not in the seat map, not on the server.
   * Clicking a seat sends nothing and marks nothing held; the seat still
   * reads `available` to every other browser, because it IS still available.
   * Only a successful POST /api/holds creates state anyone else can see.
   */
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [focusedSeatId, setFocusedSeatId] = useState<number | null>(null);
  const [holding, setHolding] = useState(false);

  /**
   * Apply a hand-off selection once, after the map loads.
   *
   * Only seats that are ACTUALLY available get selected: the assistant ranked
   * them a moment ago and someone may have taken one since, so anything now
   * held or booked is silently dropped rather than shown as chosen.
   */
  const appliedPreselection = useRef(false);
  useEffect(() => {
    if (appliedPreselection.current) return;
    if (!live.map || preselectedSeatIds.length === 0) return;
    appliedPreselection.current = true;

    const available = new Set(
      live.map.seats
        .filter((seat) => seat.status === "available")
        .map((seat) => seat.seat_id),
    );
    const usable = preselectedSeatIds.filter((id) => available.has(id));
    if (usable.length > 0) setSelected(new Set(usable));

    if (usable.length < preselectedSeatIds.length) {
      toast.show({
        title: "Some of those seats have gone",
        description:
          "They were taken while you were choosing. The rest are selected.",
      });
    }
  }, [live.map, preselectedSeatIds, toast]);

  const map = live.map;

  const selectedSeats = useMemo(() => {
    if (!map) return [];
    return map.seats.filter((seat) => selected.has(seat.seat_id));
  }, [map, selected]);

  /* ------------------------------------------------------------ selection */

  const toggle = useCallback(
    (seat: SeatMapSeat) => {
      setSelected((current) => {
        const next = new Set(current);
        if (next.has(seat.seat_id)) {
          next.delete(seat.seat_id);
          return next;
        }
        if (next.size >= MAX_SEATS_PER_HOLD) {
          toast.show({
            title: `Up to ${MAX_SEATS_PER_HOLD} seats per booking`,
            description: "Deselect one to choose a different seat.",
          });
          return current;
        }
        next.add(seat.seat_id);
        return next;
      });
    },
    [toast],
  );

  const explainBlocked = useCallback(
    (seat: SeatMapSeat) => {
      toast.show({
        title: `${seatLabel(seat)} is not available`,
        description:
          seat.status === "booked"
            ? "This seat is already booked."
            : "Someone else is holding this seat. It may free up if their hold expires.",
      });
    },
    [toast],
  );

  /* ----------------------------------------------------------------- hold */

  const acquireHold = useCallback(async () => {
    if (!map || selectedSeats.length === 0) return;
    setHolding(true);

    const requested = selectedSeats.map((seat) => seat.seat_id);

    try {
      const result = await createHold(showId, requested);
      setSelected(new Set());

      // Straight on to checkout. The hold is now the only thing keeping these
      // seats and its TTL is already running, so any screen in between spends
      // time the customer does not have.
      router.push(`/checkout/${result.hold_group_id}`);

    } catch (caught) {
      /**
       * The concurrency guarantee, surfacing.
       *
       * A 409 here is not a bug and must not look like one: it means the
       * partial unique index did its job and someone else got those exact
       * seats first. The backend names them in details.seat_ids, so the UI
       * can be specific instead of apologetic -- flash precisely those seats,
       * drop only them from the selection, and keep the rest.
       */
      if (isApiError(caught) && caught.code === "SEAT_UNAVAILABLE") {
        const lost = caught.lostSeatIds;
        const lostLabels = map.seats
          .filter((seat) => lost.includes(seat.seat_id))
          .map(seatLabel);

        live.flashSeats(lost, "lost");
        setSelected((current) => {
          const next = new Set(current);
          for (const id of lost) next.delete(id);
          return next;
        });

        toast.error(
          lost.length === 1
            ? `${lostLabels[0]} was taken`
            : `${lost.length} seats were taken`,
          lostLabels.length > 0
            ? `${lostLabels.join(", ")} went to someone else. Your other seats are still selected.`
            : "Someone else got there first.",
        );

        await live.refresh();
      } else if (isApiError(caught) && caught.code === "UNAUTHENTICATED") {
        toast.error("Sign in to hold seats", "You will come straight back here.");
        router.push(`/login?next=${encodeURIComponent(`/shows/${showId}/seats`)}`);
      } else {
        const { title, detail } = describeError(caught, "seatmap");
        toast.error(title, detail);
      }
    } finally {
      setHolding(false);
    }
  }, [map, selectedSeats, showId, toast, live, router]);

  /* --------------------------------------------------------------- states */

  if (live.loading) {
    return (
      <div className="pb-24">
        <div className="mb-6 h-8 w-64 rounded bg-surface-2" />
        <SeatMapSkeleton />
      </div>
    );
  }

  if (live.error || !map) {
    const notFound = isApiError(live.error) && live.error.code === "NOT_FOUND";
    return (
      <EmptyState
        title={notFound ? "No such show" : "Could not load the seat map"}
        description={
          notFound
            ? "This show may have been removed, or the link is wrong."
            : isApiError(live.error)
              ? live.error.message
              : "Something went wrong loading this hall."
        }
        action={
          !notFound && (
            <Button onClick={() => void live.refresh()}>Try again</Button>
          )
        }
      />
    );
  }

  return (
    <div className="pb-28">
      <header className="mb-5 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="font-display text-2xl leading-tight tracking-tight text-text">
            {map.event_title}
          </h1>
          <p className="mt-1 text-[13px] text-muted">
            {map.venue_name} &middot; {map.screen_name} &middot;{" "}
            {new Date(map.starts_at).toLocaleString(undefined, {
              weekday: "short",
              day: "numeric",
              month: "short",
              hour: "2-digit",
              minute: "2-digit",
            })}
            {map.format ? ` · ${map.format}` : ""} &middot; {map.language}
          </p>
        </div>

        <div className="flex items-center gap-2">
          <ConnectionIndicator transport={live.transport} />
          <span
            className="rounded-full border border-border bg-surface px-2.5 py-1 text-[11px] uppercase tracking-[0.12em] text-muted"
            title="Monotonic version of this show's seat state. Both the poll and the stream carry it."
          >
            v{map.seat_version}
          </span>
        </div>
      </header>

      <div className="rounded-xl border border-border bg-surface p-4 sm:p-6">
        <SeatMapCanvas
          map={map}
          selected={selected}
          flashes={live.flashes}
          onToggle={toggle}
          onBlocked={explainBlocked}
          focusedSeatId={focusedSeatId}
          onFocusSeat={setFocusedSeatId}
        />
      </div>

      <WaitlistPanel map={map} onJoined={() => void live.refresh()} />

      <div className="mt-5 flex flex-wrap items-center justify-between gap-4">
        <SeatLegend />
        <p className="text-[12px] text-muted">
          Arrow keys move between seats, Enter selects. Scroll or pinch to zoom.
        </p>
      </div>

      <SelectionBar
        map={map}
        selectedSeats={selectedSeats}
        onClear={() => setSelected(new Set())}
        onHold={() => void acquireHold()}
        holding={holding}
      />
    </div>
  );
}
