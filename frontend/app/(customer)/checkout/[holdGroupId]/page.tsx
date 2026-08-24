"use client";

import { use, useCallback, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Countdown } from "@/components/ui/Countdown";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { useToast } from "@/components/ui/Toast";
import { RequireAuth } from "@/components/auth/RequireRole";
import { confirmHold, fetchHold } from "@/lib/bookings";
import { describeError } from "@/lib/errors";
import { isApiError } from "@/lib/api";
import { formatMoney, seatLabel } from "@/lib/seatmap";
import type { HeldSeat } from "@/lib/types";

export default function CheckoutPage({
  params,
}: {
  params: Promise<{ holdGroupId: string }>;
}) {
  const { holdGroupId } = use(params);
  return (
    <RequireAuth>
      <Checkout holdGroupId={holdGroupId} />
    </RequireAuth>
  );
}

function Checkout({ holdGroupId }: { holdGroupId: string }) {
  const router = useRouter();
  const toast = useToast();
  const [expired, setExpired] = useState(false);
  const [confirming, setConfirming] = useState(false);

  /**
   * One key for this checkout, generated once and reused across retries.
   *
   * That is the whole point of idempotency: if the first confirm times out,
   * the retry must return the SAME booking rather than attempt a second one.
   * A key regenerated per attempt would defeat it entirely.
   */
  const idempotencyKey = useRef<string>(
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : `checkout-${holdGroupId}`,
  );

  const holdQuery = useQuery({
    queryKey: ["hold", holdGroupId],
    queryFn: () => fetchHold(holdGroupId),
    // The hold is the authority on its own life; a stale cached copy would
    // show time remaining on something already gone.
    staleTime: 0,
    retry: false,
  });

  const hold = holdQuery.data;

  const byCategory = useMemo(() => {
    const groups = new Map<string, { seats: HeldSeat[]; price: number }>();
    for (const seat of hold?.seats ?? []) {
      const existing = groups.get(seat.category_name);
      if (existing) existing.seats.push(seat);
      else groups.set(seat.category_name, { seats: [seat], price: Number(seat.price) });
    }
    return [...groups.entries()];
  }, [hold]);

  const confirm = useCallback(async () => {
    if (!hold || expired) return;
    setConfirming(true);
    try {
      const booking = await confirmHold(holdGroupId, idempotencyKey.current);
      toast.success(
        "Booking confirmed",
        `${booking.reference} — a ticket is on its way to your inbox.`,
      );
      router.replace(`/bookings/${booking.reference}`);
    } catch (caught) {
      if (isApiError(caught) && caught.code === "HOLD_EXPIRED") {
        // Not a failure to apologise for: the hold did its job and released
        // the seats so someone else could have them.
        setExpired(true);
        const { title, detail } = describeError(caught, "checkout");
        toast.error(title, detail);
      } else {
        const { title, detail } = describeError(caught, "checkout");
        toast.error(title, detail);
      }
      setConfirming(false);
    }
  }, [hold, expired, holdGroupId, toast, router]);

  /* --------------------------------------------------------------- states */

  if (holdQuery.isLoading) return <CheckoutSkeleton />;

  /**
   * 404 or 410 here means the hold is simply gone -- swept, released, or
   * never real. Explain it and hand back a route rather than leaving someone
   * on a page that can never work.
   */
  if (holdQuery.isError) {
    const error = holdQuery.error;
    const gone =
      isApiError(error) &&
      (error.code === "NOT_FOUND" || error.code === "HOLD_EXPIRED");
    const { title, detail } = describeError(error, "checkout");

    return (
      <EmptyState
        title={gone ? "This hold is no longer active" : title}
        description={
          gone
            ? "It expired or was released, so the seats went back on sale. Nothing was booked and you have not been charged."
            : detail
        }
        action={<Button onClick={() => router.push("/")}>Find another show</Button>}
      />
    );
  }

  if (!hold) return null;

  const total = Number(hold.total);

  return (
    <div className="mx-auto max-w-2xl">
      <p className="text-[11px] uppercase tracking-[0.18em] text-muted">
        Review and confirm
      </p>
      <h1 className="mt-2 font-display text-3xl leading-tight tracking-tight text-text">
        {hold.seats.length} {hold.seats.length === 1 ? "seat" : "seats"} held
      </h1>

      {/* The countdown. Prominent because it is the single most important
          fact on this page, but it shifts colour under a minute rather than
          flashing -- this is a deadline, not an alarm, and the seats going
          back on sale is a normal outcome. */}
      <div className="mt-5 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border bg-surface px-4 py-3.5">
        <div>
          <p className="text-[11px] uppercase tracking-[0.12em] text-muted">
            {expired ? "Hold expired" : "Seats held for"}
          </p>
          <Countdown
            expiresAt={hold.expires_at}
            warnAtSeconds={60}
            className="mt-0.5 text-2xl"
            onExpire={() => setExpired(true)}
          />
        </div>
        <p className="max-w-[19rem] text-[12px] leading-relaxed text-muted">
          {expired
            ? "The seats have gone back on sale."
            : "After this, the seats are released for other people to book."}
        </p>
      </div>

      {expired && (
        <div
          role="alert"
          className="mt-4 rounded-xl border border-danger/25 bg-danger-soft px-4 py-3.5"
        >
          <p className="text-sm text-danger">Your hold expired</p>
          <p className="mt-1 text-[13px] leading-relaxed text-muted">
            No booking was made and you have not been charged. The seats are
            back on the map and may still be free.
          </p>
          <Button
            variant="ghost"
            size="sm"
            className="mt-3"
            onClick={() => router.push(`/shows/${hold.show_id}/seats`)}
          >
            Back to the seat map
          </Button>
        </div>
      )}

      <Card className="mt-4">
        <div className="border-b border-border p-5">
          <h2 className="font-display text-lg leading-tight text-text">
            {/* The hold response does not carry the event title, so the show
                id is the honest identifier until the booking exists. */}
            Show #{hold.show_id}
          </h2>
          <p className="mt-1 text-[13px] text-muted">
            Seats {hold.seats.map(seatLabel).join(", ")}
          </p>
        </div>

        <div className="p-5">
          <ul className="space-y-2.5">
            {byCategory.map(([name, group]) => (
              <li key={name} className="flex items-baseline justify-between gap-4">
                <span className="text-sm text-text">
                  {name}{" "}
                  <span className="text-muted">
                    &times;{group.seats.length} &middot;{" "}
                    {group.seats.map(seatLabel).join(", ")}
                  </span>
                </span>
                <span className="shrink-0 text-sm tabular-nums text-muted">
                  {formatMoney(group.price * group.seats.length)}
                </span>
              </li>
            ))}
          </ul>

          {/* No fees, no taxes, no service line. The total is the sum of the
              seat prices and nothing else -- inventing a line item would be
              inventing a charge. */}
          <div className="mt-4 flex items-baseline justify-between border-t border-border pt-4">
            <span className="text-sm text-text">Total</span>
            <span className="font-display text-2xl tabular-nums text-accent">
              {formatMoney(total)}
            </span>
          </div>
        </div>
      </Card>

      <Button
        size="lg"
        fullWidth
        className="mt-5"
        loading={confirming}
        disabled={expired}
        onClick={() => void confirm()}
      >
        {expired ? "Hold expired" : `Confirm booking · ${formatMoney(total)}`}
      </Button>

      <p className="mt-3 text-center text-[12px] text-muted">
        Payment is mocked for this build — confirming books the seats
        immediately.
      </p>
    </div>
  );
}

function CheckoutSkeleton() {
  return (
    <div className="mx-auto max-w-2xl">
      <Skeleton className="h-4 w-32" />
      <Skeleton className="mt-3 h-9 w-56" />
      <Skeleton className="mt-5 h-20 w-full rounded-xl" />
      <Skeleton className="mt-4 h-56 w-full rounded-xl" />
      <Skeleton className="mt-5 h-12 w-full rounded-lg" />
    </div>
  );
}
