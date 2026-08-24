"use client";

import { use } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { TicketQr } from "@/components/booking/TicketQr";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { RequireAuth } from "@/components/auth/RequireRole";
import { fetchBooking } from "@/lib/bookings";
import { describeError } from "@/lib/errors";
import { formatLabel } from "@/lib/catalog";
import { formatMoney, seatLabel } from "@/lib/seatmap";

/**
 * A booking, in full.
 *
 * Deliberately a real page rather than a post-confirmation screen: it is
 * reachable from booking history at any time, survives a refresh, and is what
 * someone opens at the door. Nothing here depends on having just come from
 * checkout.
 */
export default function BookingPage({
  params,
}: {
  params: Promise<{ reference: string }>;
}) {
  const { reference } = use(params);
  return (
    <RequireAuth>
      <BookingDetail reference={reference} />
    </RequireAuth>
  );
}

function BookingDetail({ reference }: { reference: string }) {
  const router = useRouter();
  const query = useQuery({
    queryKey: ["booking", reference],
    queryFn: () => fetchBooking(reference),
    retry: false,
  });

  if (query.isLoading) return <BookingSkeleton />;

  if (query.isError) {
    const { title, detail } = describeError(query.error, "generic");
    return (
      <EmptyState
        title={title}
        description={detail}
        action={<Button onClick={() => router.push("/profile")}>Your bookings</Button>}
      />
    );
  }

  const booking = query.data!;
  const cancelled = booking.status === "cancelled";
  const starts = new Date(booking.show.starts_at);

  return (
    <div className="mx-auto max-w-2xl">
      <div className="flex items-center gap-3">
        <Badge tone={cancelled ? "danger" : "success"}>
          {cancelled ? "Cancelled" : "Confirmed"}
        </Badge>
        {booking.checked_in_at && <Badge tone="neutral">Checked in</Badge>}
      </div>

      <h1 className="mt-3 font-display text-3xl leading-tight tracking-tight text-text">
        {booking.show.event_title}
      </h1>
      <p className="mt-1.5 text-[15px] text-muted">
        {booking.show.venue_name} &middot; {booking.show.screen_name}
      </p>

      <Card className="mt-6">
        <div className="flex flex-col gap-6 p-6 sm:flex-row sm:items-center">
          <div className="shrink-0">
            <TicketQr
              reference={booking.reference}
              signature={cancelled ? null : booking.qr_signature}
            />
          </div>

          <div className="min-w-0 flex-1">
            <p className="text-[11px] uppercase tracking-[0.14em] text-muted">
              Booking reference
            </p>
            {/* Large and selectable: this is the thing someone reads down a
                phone line or types at a counter when a scanner fails. */}
            <p className="mt-1 select-all font-display text-3xl tracking-[0.06em] text-accent">
              {booking.reference}
            </p>

            <dl className="mt-5 space-y-2 text-[13px]">
              <Row label="When">
                {starts.toLocaleString([], {
                  weekday: "short",
                  day: "numeric",
                  month: "short",
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </Row>
              <Row label="Format">
                {booking.show.language} &middot; {formatLabel(booking.show.format)}
              </Row>
              <Row label="Seats">
                {booking.seats.map(seatLabel).join(", ")}
              </Row>
            </dl>
          </div>
        </div>

        <div className="border-t border-border p-6">
          <ul className="space-y-2">
            {booking.seats.map((seat) => (
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
            <span className="text-sm text-text">
              {cancelled ? "Refunded" : "Total paid"}
            </span>
            <span className="font-display text-2xl tabular-nums text-accent">
              {formatMoney(Number(booking.total))}
            </span>
          </div>
        </div>
      </Card>

      {cancelled ? (
        <p className="mt-4 text-center text-[13px] text-muted">
          This booking was cancelled
          {booking.cancelled_at
            ? ` on ${new Date(booking.cancelled_at).toLocaleDateString()}`
            : ""}
          . The seats went back on sale.
        </p>
      ) : (
        <p className="mt-4 text-center text-[13px] text-muted">
          A copy of this ticket has been emailed to you. Show the QR code at the
          door.
        </p>
      )}

      <div className="mt-6 flex justify-center">
        <Link
          href="/profile"
          className="text-[13px] text-muted underline decoration-border underline-offset-4 transition-colors hover:text-text hover:decoration-accent"
        >
          All your bookings
        </Link>
      </div>
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-3">
      <dt className="w-16 shrink-0 text-muted">{label}</dt>
      <dd className="text-text">{children}</dd>
    </div>
  );
}

function BookingSkeleton() {
  return (
    <div className="mx-auto max-w-2xl">
      <Skeleton className="h-5 w-24" />
      <Skeleton className="mt-3 h-9 w-2/3" />
      <Skeleton className="mt-2 h-4 w-1/2" />
      <Skeleton className="mt-6 h-72 w-full rounded-xl" />
    </div>
  );
}
