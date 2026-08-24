"use client";

import { use, useCallback, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Countdown } from "@/components/ui/Countdown";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { useToast } from "@/components/ui/Toast";
import { useAuth } from "@/components/auth/AuthProvider";
import { claimOffer, fetchOffer } from "@/lib/bookings";
import { describeError } from "@/lib/errors";
import { isApiError } from "@/lib/api";
import { formatLabel } from "@/lib/catalog";
import { formatMoney, seatLabel } from "@/lib/seatmap";

/**
 * The page an offer email links to.
 *
 * PUBLIC to read. The token in the URL is the credential, and the backend
 * treats it that way -- an expired token, an already-claimed one and a
 * fabricated one all answer OFFER_EXPIRED identically, so the token space
 * cannot be probed by watching which errors come back.
 *
 * Claiming needs the account the offer was made to, which is a different
 * thing from reading it: someone should be able to see what they have been
 * offered, and how long they have, before being asked to sign in.
 */
export default function OfferPage({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = use(params);
  const router = useRouter();
  const toast = useToast();
  const { user, loading: authLoading } = useAuth();

  const [expired, setExpired] = useState(false);
  const [claiming, setClaiming] = useState(false);

  const query = useQuery({
    queryKey: ["offer", token],
    queryFn: () => fetchOffer(token),
    retry: false,
    staleTime: 0,
  });

  const claim = useCallback(async () => {
    setClaiming(true);
    try {
      const booking = await claimOffer(token);
      toast.success(
        "Seats claimed",
        `${booking.reference} — a ticket is on its way to your inbox.`,
      );
      router.replace(`/bookings/${booking.reference}`);
    } catch (caught) {
      if (isApiError(caught) && caught.code === "OFFER_EXPIRED") setExpired(true);
      const { title, detail } = describeError(caught, "offer");
      toast.error(title, detail);
      setClaiming(false);
    }
  }, [token, toast, router]);

  if (query.isLoading || authLoading) return <OfferSkeleton />;

  /**
   * A lapsed offer is not an error to apologise for -- it is the mechanism
   * working. The seats were time-limited precisely so they could move on to
   * the next person quickly.
   */
  if (query.isError) {
    const lapsed = isApiError(query.error) && query.error.code === "OFFER_EXPIRED";
    const { title, detail } = describeError(query.error, "offer");
    return (
      <EmptyState
        title={lapsed ? "This offer has lapsed" : title}
        description={
          lapsed
            ? "Offers are held for a short window so the seats can move on quickly. These have gone to the next person waiting."
            : detail
        }
        action={
          <Button onClick={() => router.push("/profile")}>
            Your waitlist
          </Button>
        }
      />
    );
  }

  const offer = query.data!;
  const total = Number(offer.total);
  const dead = expired;

  return (
    <div className="mx-auto max-w-2xl">
      <p className="text-[11px] uppercase tracking-[0.18em] text-accent">
        Seats available for you
      </p>
      <h1 className="mt-2 font-display text-3xl leading-tight tracking-tight text-text">
        {offer.show.event_title}
      </h1>
      <p className="mt-1.5 text-[15px] text-muted">
        {offer.show.venue_name} &middot; {offer.show.screen_name} &middot;{" "}
        {new Date(offer.show.starts_at).toLocaleString([], {
          weekday: "short",
          day: "numeric",
          month: "short",
          hour: "2-digit",
          minute: "2-digit",
        })}
      </p>

      <div className="mt-5 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-accent/25 bg-accent-soft px-4 py-3.5">
        <div>
          <p className="text-[11px] uppercase tracking-[0.12em] text-muted">
            {dead ? "Offer lapsed" : "Claim within"}
          </p>
          <Countdown
            expiresAt={offer.expires_at}
            warnAtSeconds={120}
            className="mt-0.5 text-2xl"
            onExpire={() => setExpired(true)}
          />
        </div>
        <p className="max-w-[19rem] text-[12px] leading-relaxed text-muted">
          {dead
            ? "These seats have gone to the next person on the waitlist."
            : "Someone cancelled and you were next in line. These seats are held for you until the timer runs out."}
        </p>
      </div>

      <Card className="mt-4">
        <div className="border-b border-border p-5">
          <p className="text-[11px] uppercase tracking-[0.12em] text-muted">
            {offer.category_name} &middot; {offer.show.language} &middot;{" "}
            {formatLabel(offer.show.format)}
          </p>
          <p className="mt-1.5 text-sm text-text">
            Seats {offer.seats.map(seatLabel).join(", ")}
          </p>
        </div>

        <div className="p-5">
          <ul className="space-y-2">
            {offer.seats.map((seat) => (
              <li
                key={seat.seat_id}
                className="flex items-baseline justify-between gap-4 text-[13px]"
              >
                <span className="text-text">
                  {seatLabel(seat)}{" "}
                  <span className="text-muted">{seat.category_name}</span>
                </span>
                <span className="tabular-nums text-muted">
                  {formatMoney(Number(seat.price))}
                </span>
              </li>
            ))}
          </ul>
          <div className="mt-4 flex items-baseline justify-between border-t border-border pt-4">
            <span className="text-sm text-text">Total</span>
            <span className="font-display text-2xl tabular-nums text-accent">
              {formatMoney(total)}
            </span>
          </div>
        </div>
      </Card>

      {user ? (
        <Button
          size="lg"
          fullWidth
          className="mt-5"
          loading={claiming}
          disabled={dead}
          onClick={() => void claim()}
        >
          {dead ? "Offer lapsed" : `Claim these seats · ${formatMoney(total)}`}
        </Button>
      ) : (
        <div className="mt-5 rounded-xl border border-border bg-surface p-5 text-center">
          <p className="text-sm text-text">Sign in to claim these seats</p>
          <p className="mt-1 text-[13px] text-muted">
            Use the account the offer email was sent to. You will come straight
            back here.
          </p>
          <Button
            size="lg"
            fullWidth
            className="mt-4"
            disabled={dead}
            onClick={() =>
              // Round-trip back to this exact offer after signing in; the
              // clock keeps running while they do it.
              router.push(`/login?next=${encodeURIComponent(`/offers/${token}`)}`)
            }
          >
            Sign in to claim
          </Button>
        </div>
      )}
    </div>
  );
}

function OfferSkeleton() {
  return (
    <div className="mx-auto max-w-2xl">
      <Skeleton className="h-4 w-40" />
      <Skeleton className="mt-3 h-9 w-2/3" />
      <Skeleton className="mt-2 h-4 w-1/2" />
      <Skeleton className="mt-5 h-20 w-full rounded-xl" />
      <Skeleton className="mt-4 h-48 w-full rounded-xl" />
      <Skeleton className="mt-5 h-12 w-full rounded-lg" />
    </div>
  );
}
