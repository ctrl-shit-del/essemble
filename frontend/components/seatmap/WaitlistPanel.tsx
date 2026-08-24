"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { useAuth } from "@/components/auth/AuthProvider";
import { joinWaitlist } from "@/lib/bookings";
import { describeError } from "@/lib/errors";
import { MAX_SEATS_PER_HOLD, formatMoney } from "@/lib/seatmap";
import type { SeatMap, SeatMapCategory } from "@/lib/types";
import { cn } from "@/lib/cn";

/**
 * Sold-out categories, and the waitlist offered in their place.
 *
 * A category with nothing left has no selection affordance to give -- every
 * seat in it is already unclickable -- so the space it would occupy becomes
 * the way in to the waitlist instead. Showing "Join waitlist" only where it
 * can actually be used is the point: the backend answers NOT_SOLD_OUT if a
 * seat is still free, so offering the button on a category with availability
 * would be offering a button that fails.
 */
export function WaitlistPanel({
  map,
  onJoined,
}: {
  map: SeatMap;
  onJoined?: () => void;
}) {
  const [target, setTarget] = useState<SeatMapCategory | null>(null);

  const soldOut = map.categories.filter((category) => {
    const seats = map.seats.filter((seat) => seat.category_id === category.id);
    return seats.length > 0 && seats.every((seat) => seat.status !== "available");
  });

  if (soldOut.length === 0) return null;

  return (
    <>
      <section className="mt-5 rounded-xl border border-border bg-surface p-5">
        <div className="flex items-center gap-2">
          <h2 className="font-display text-base text-text">Sold out</h2>
          <Badge tone="neutral">
            {soldOut.length} {soldOut.length === 1 ? "category" : "categories"}
          </Badge>
        </div>
        <p className="mt-1.5 text-[13px] leading-relaxed text-muted">
          Join the waitlist and you get first refusal if someone cancels — the
          seats are offered to you before they go back on general sale.
        </p>

        <ul className="mt-4 space-y-2">
          {soldOut.map((category) => (
            <li
              key={category.id}
              className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border bg-surface-2 px-4 py-3"
            >
              <div>
                <p className="text-sm text-text">{category.name}</p>
                <p className="text-[12px] text-muted">
                  {formatMoney(Number(category.price))} · every seat taken
                </p>
              </div>
              <Button size="sm" onClick={() => setTarget(category)}>
                Join waitlist
              </Button>
            </li>
          ))}
        </ul>
      </section>

      <JoinDialog
        map={map}
        category={target}
        onClose={() => setTarget(null)}
        onJoined={onJoined}
      />
    </>
  );
}

function JoinDialog({
  map,
  category,
  onClose,
  onJoined,
}: {
  map: SeatMap;
  category: SeatMapCategory | null;
  onClose: () => void;
  onJoined?: () => void;
}) {
  const [qty, setQty] = useState(2);
  const toast = useToast();
  const { user } = useAuth();
  const queryClient = useQueryClient();

  const mutation = useMutation({
    mutationFn: () => joinWaitlist(map.show_id, category!.id, qty),
    onSuccess: async (entry) => {
      toast.success(
        "You are on the waitlist",
        entry.position
          ? `Position ${entry.position} for ${entry.qty} ${
              entry.qty === 1 ? "seat" : "seats"
            } in ${entry.category_name}.`
          : `${entry.qty} ${entry.qty === 1 ? "seat" : "seats"} in ${entry.category_name}.`,
      );
      await queryClient.invalidateQueries({ queryKey: ["waitlist"] });
      onJoined?.();
      onClose();
    },
    onError: (error) => {
      const { title, detail } = describeError(error, "waitlist");
      toast.error(title, detail);
    },
  });

  if (!category) return null;

  return (
    <Modal
      open
      onClose={mutation.isPending ? () => {} : onClose}
      title={`Waitlist for ${category.name}`}
      description="If someone cancels, the seats are offered to the longest-waiting person who needs that many."
      dismissible={!mutation.isPending}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          {user ? (
            <Button loading={mutation.isPending} onClick={() => mutation.mutate()}>
              Join waitlist
            </Button>
          ) : (
            <Button onClick={() => (window.location.href = "/login")}>
              Sign in to join
            </Button>
          )}
        </>
      }
    >
      <p className="text-[13px] text-muted">How many seats do you need?</p>
      <div className="mt-3 flex flex-wrap gap-2">
        {Array.from({ length: Math.min(6, MAX_SEATS_PER_HOLD) }, (_, i) => i + 1).map(
          (value) => (
            <button
              key={value}
              type="button"
              onClick={() => setQty(value)}
              aria-pressed={qty === value}
              className={cn(
                "h-10 w-10 rounded-lg border text-sm transition-colors duration-150",
                qty === value
                  ? "border-accent bg-accent-soft text-accent"
                  : "border-border bg-surface text-text hover:border-border-strong",
              )}
            >
              {value}
            </button>
          ),
        )}
      </div>
      <p className="mt-3 text-[12px] leading-relaxed text-muted">
        You will only be offered seats when at least this many free up at once,
        so asking for more than you need means waiting longer.
      </p>
    </Modal>
  );
}
