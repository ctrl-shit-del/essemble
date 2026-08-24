"use client";

import { Button } from "@/components/ui/Button";
import { MAX_SEATS_PER_HOLD, categoryName, formatMoney, priceOf, seatLabel } from "@/lib/seatmap";
import type { SeatMap, SeatMapSeat } from "@/lib/types";
import { cn } from "@/lib/cn";

/**
 * Sticky glass bar for the current selection.
 *
 * One of the five sanctioned uses of glass: it floats over the map, and the
 * seats behind it staying faintly visible is the point -- a solid bar would
 * hide the bottom rows of the hall you are choosing from.
 *
 * Everything shown is computed from the client-side selection and the
 * category prices in the seat map. Nothing here has been sent to the server:
 * until the hold succeeds, this is a shopping list, not a reservation.
 */
export function SelectionBar({
  map,
  selectedSeats,
  onClear,
  onHold,
  holding,
  disabled,
}: {
  map: SeatMap;
  selectedSeats: SeatMapSeat[];
  onClear: () => void;
  onHold: () => void;
  holding: boolean;
  disabled?: boolean;
}) {
  const count = selectedSeats.length;
  if (count === 0) return null;

  // Grouped by category so the breakdown explains the total rather than
  // asking the customer to trust one number.
  const byCategory = new Map<number, SeatMapSeat[]>();
  for (const seat of selectedSeats) {
    const bucket = byCategory.get(seat.category_id);
    if (bucket) bucket.push(seat);
    else byCategory.set(seat.category_id, [seat]);
  }

  const total = selectedSeats.reduce(
    (sum, seat) => sum + priceOf(map, seat.category_id),
    0,
  );

  const atLimit = count >= MAX_SEATS_PER_HOLD;

  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-0 z-40 p-4">
      <div className="glass pointer-events-auto mx-auto flex max-w-5xl flex-col gap-4 rounded-2xl p-4 sm:flex-row sm:items-center sm:justify-between animate-[essemble-fade-in_200ms_var(--ease-out-soft)]">
        <div className="min-w-0">
          <div className="flex items-baseline gap-2">
            <span className="font-display text-lg text-text">
              {count} {count === 1 ? "seat" : "seats"}
            </span>
            {atLimit && (
              <span className="text-[11px] uppercase tracking-[0.12em] text-accent">
                max reached
              </span>
            )}
          </div>

          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1">
            {[...byCategory.entries()].map(([categoryId, seats]) => (
              <span key={categoryId} className="text-[13px] text-muted">
                <span className="text-text">{categoryName(map, categoryId)}</span>{" "}
                &times;{seats.length}{" "}
                <span className="text-muted/70">
                  {seats.map(seatLabel).join(", ")}
                </span>
              </span>
            ))}
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-4">
          <div className="text-right">
            <p className="text-[11px] uppercase tracking-[0.12em] text-muted">
              Total
            </p>
            {/* Key metric -- one of amber's sanctioned uses. */}
            <p className="font-display text-xl leading-tight text-accent tabular-nums">
              {formatMoney(total)}
            </p>
          </div>

          <Button variant="ghost" size="md" onClick={onClear} disabled={holding}>
            Clear
          </Button>

          <Button
            size="md"
            onClick={onHold}
            loading={holding}
            disabled={disabled}
            className={cn("min-w-[8.5rem]")}
          >
            Hold seats
          </Button>
        </div>
      </div>
    </div>
  );
}
