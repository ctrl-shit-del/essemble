"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Countdown } from "@/components/ui/Countdown";
import { EmptyState } from "@/components/ui/EmptyState";
import { Modal } from "@/components/ui/Modal";
import { Skeleton } from "@/components/ui/Skeleton";
import { useToast } from "@/components/ui/Toast";
import { RequireAuth } from "@/components/auth/RequireRole";
import { useAuth } from "@/components/auth/AuthProvider";
import {
  cancelBooking,
  fetchBookings,
  fetchWaitlist,
  leaveWaitlist,
  splitBookings,
} from "@/lib/bookings";
import { describeError } from "@/lib/errors";
import { formatMoney, seatLabel } from "@/lib/seatmap";
import type { Booking, WaitlistEntry } from "@/lib/types";
import { cn } from "@/lib/cn";

const TABS = [
  { id: "upcoming", label: "Upcoming" },
  { id: "history", label: "History" },
  { id: "waitlist", label: "Waitlist" },
  { id: "settings", label: "Settings" },
] as const;

type TabId = (typeof TABS)[number]["id"];

function isTabId(value: string | null): value is TabId {
  return TABS.some((tab) => tab.id === value);
}

export default function ProfilePage() {
  return (
    <RequireAuth>
      {/* useSearchParams needs a boundary or the whole route opts out of
          static rendering. */}
      <Suspense fallback={null}>
        <Profile />
      </Suspense>
    </RequireAuth>
  );
}

function Profile() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const requested = searchParams.get("tab");

  const [tab, setTab] = useState<TabId>(
    isTabId(requested) ? requested : "upcoming",
  );
  const { user } = useAuth();

  // Follow the URL when it changes under us -- the profile menu links
  // between tabs while already on this page, and without this the panel
  // would appear to do nothing.
  useEffect(() => {
    if (isTabId(requested) && requested !== tab) setTab(requested);
    // Deliberately not depending on `tab`: this reacts to the URL, and
    // including it would fight the click handler below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requested]);

  /** Keep the URL shareable, without pushing a history entry per tab. */
  const selectTab = (next: TabId) => {
    setTab(next);
    router.replace(next === "upcoming" ? "/profile" : `/profile?tab=${next}`, {
      scroll: false,
    });
  };

  const bookingsQuery = useQuery({
    queryKey: ["bookings"],
    queryFn: () => fetchBookings(),
  });

  const waitlistQuery = useQuery({
    queryKey: ["waitlist"],
    queryFn: () => fetchWaitlist(),
  });

  const { upcoming, past } = useMemo(
    () => splitBookings(bookingsQuery.data ?? []),
    [bookingsQuery.data],
  );

  const liveWaitlist = (waitlistQuery.data ?? []).filter(
    (entry) => entry.state === "waiting" || entry.state === "offered",
  );

  const counts: Record<TabId, number | null> = {
    upcoming: upcoming.length,
    history: past.length,
    waitlist: liveWaitlist.length,
    settings: null,
  };

  return (
    <div>
      <h1 className="font-display text-3xl leading-tight tracking-tight text-text">
        {user?.name}
      </h1>
      <p className="mt-1 text-[13px] text-muted">{user?.email}</p>

      <div className="mt-8 border-b border-border">
        <ul className="flex gap-1 overflow-x-auto" role="tablist">
          {TABS.map((item) => {
            const active = tab === item.id;
            return (
              <li key={item.id}>
                <button
                  type="button"
                  role="tab"
                  aria-selected={active}
                  onClick={() => selectTab(item.id)}
                  className={cn(
                    "relative whitespace-nowrap px-4 py-3 text-sm transition-colors duration-150",
                    active ? "text-text" : "text-muted hover:text-text",
                  )}
                >
                  {item.label}
                  {counts[item.id] !== null && counts[item.id]! > 0 && (
                    <span className="ml-1.5 text-[11px] text-muted">
                      {counts[item.id]}
                    </span>
                  )}
                  <span
                    aria-hidden="true"
                    className={cn(
                      "absolute inset-x-3 -bottom-px h-0.5 bg-accent transition-opacity",
                      active ? "opacity-100" : "opacity-0",
                    )}
                  />
                </button>
              </li>
            );
          })}
        </ul>
      </div>

      <div className="mt-6">
        {tab === "upcoming" && (
          <BookingList
            bookings={upcoming}
            loading={bookingsQuery.isLoading}
            cancellable
            emptyTitle="Nothing booked yet"
            emptyDescription="When you book a show it will appear here with its ticket."
          />
        )}
        {tab === "history" && (
          <BookingList
            bookings={past}
            loading={bookingsQuery.isLoading}
            emptyTitle="No past bookings"
            emptyDescription="Shows you have been to, and anything cancelled, land here."
          />
        )}
        {tab === "waitlist" && (
          <WaitlistList
            entries={liveWaitlist}
            loading={waitlistQuery.isLoading}
          />
        )}
        {tab === "settings" && <Settings />}
      </div>
    </div>
  );
}

/* -------------------------------------------------------------- bookings */

function BookingList({
  bookings,
  loading,
  cancellable = false,
  emptyTitle,
  emptyDescription,
}: {
  bookings: Booking[];
  loading: boolean;
  cancellable?: boolean;
  emptyTitle: string;
  emptyDescription: string;
}) {
  const [pendingCancel, setPendingCancel] = useState<Booking | null>(null);

  if (loading) {
    return (
      <div className="space-y-3">
        {Array.from({ length: 3 }).map((_, index) => (
          <Skeleton key={index} className="h-28 w-full rounded-xl" />
        ))}
      </div>
    );
  }

  if (bookings.length === 0) {
    return (
      <EmptyState
        title={emptyTitle}
        description={emptyDescription}
        action={
          <Link href="/">
            <Button>See what&rsquo;s on</Button>
          </Link>
        }
      />
    );
  }

  return (
    <>
      <ul className="space-y-3">
        {bookings.map((booking) => (
          <li key={booking.reference}>
            <Card interactive>
              <div className="flex flex-wrap items-start justify-between gap-4 p-5">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <Link
                      href={`/bookings/${booking.reference}`}
                      className="font-display text-lg leading-tight text-text transition-colors hover:text-accent"
                    >
                      {booking.show.event_title}
                    </Link>
                    {booking.status === "cancelled" && (
                      <Badge tone="danger">Cancelled</Badge>
                    )}
                    {booking.checked_in_at && <Badge tone="neutral">Used</Badge>}
                  </div>

                  <p className="mt-1 text-[13px] text-muted">
                    {new Date(booking.show.starts_at).toLocaleString([], {
                      weekday: "short",
                      day: "numeric",
                      month: "short",
                      hour: "2-digit",
                      minute: "2-digit",
                    })}{" "}
                    &middot; {booking.show.venue_name} &middot;{" "}
                    {booking.show.screen_name}
                  </p>
                  <p className="mt-1 text-[13px] text-muted">
                    {booking.seats.map(seatLabel).join(", ")} &middot;{" "}
                    <span className="text-accent">{booking.reference}</span>
                  </p>
                </div>

                <div className="flex shrink-0 items-center gap-3">
                  <span className="font-display text-lg tabular-nums text-text">
                    {formatMoney(Number(booking.total))}
                  </span>
                  {cancellable && booking.status === "confirmed" && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => setPendingCancel(booking)}
                    >
                      Cancel
                    </Button>
                  )}
                </div>
              </div>
            </Card>
          </li>
        ))}
      </ul>

      <CancelDialog
        booking={pendingCancel}
        onClose={() => setPendingCancel(null)}
      />
    </>
  );
}

/**
 * Cancellation, with the seats named.
 *
 * Naming them matters: someone with two bookings for the same film needs to
 * see WHICH seats are about to go before they agree, not just the title.
 */
function CancelDialog({
  booking,
  onClose,
}: {
  booking: Booking | null;
  onClose: () => void;
}) {
  const toast = useToast();
  const queryClient = useQueryClient();

  const mutation = useMutation({
    mutationFn: (reference: string) => cancelBooking(reference),
    onSuccess: async (result) => {
      const offers = result.offers_created.length;
      toast.success(
        "Booking cancelled",
        offers > 0
          ? `${formatMoney(Number(result.refund_amount))} refunded. ${offers} ${
              offers === 1 ? "person" : "people"
            } on the waitlist ${offers === 1 ? "has" : "have"} been offered your seats.`
          : `${formatMoney(Number(result.refund_amount))} refunded. The seats are back on sale.`,
      );
      await queryClient.invalidateQueries({ queryKey: ["bookings"] });
      onClose();
    },
    onError: (error) => {
      // The 409 inside the cutoff is the important one -- it is a rule, not a
      // fault, and deserves the explanation rather than a generic failure.
      const { title, detail } = describeError(error, "cancel");
      toast.error(title, detail);
    },
  });

  if (!booking) return null;

  return (
    <Modal
      open
      onClose={mutation.isPending ? () => {} : onClose}
      title="Cancel this booking?"
      description="The seats go back on sale immediately, and may be offered to someone on the waitlist."
      dismissible={!mutation.isPending}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={mutation.isPending}>
            Keep it
          </Button>
          <Button
            variant="danger"
            loading={mutation.isPending}
            onClick={() => mutation.mutate(booking.reference)}
          >
            Cancel booking
          </Button>
        </>
      }
    >
      <div className="rounded-lg border border-border bg-surface p-4">
        <p className="font-display text-base text-text">
          {booking.show.event_title}
        </p>
        <p className="mt-1 text-[13px] text-muted">
          {new Date(booking.show.starts_at).toLocaleString([], {
            weekday: "short",
            day: "numeric",
            month: "short",
            hour: "2-digit",
            minute: "2-digit",
          })}{" "}
          &middot; {booking.show.venue_name}
        </p>
        <p className="mt-3 text-sm text-text">
          Seats{" "}
          <span className="text-accent">
            {booking.seats.map(seatLabel).join(", ")}
          </span>
        </p>
        <p className="mt-1 text-[13px] text-muted">
          {formatMoney(Number(booking.total))} will be refunded.
        </p>
      </div>
    </Modal>
  );
}

/* -------------------------------------------------------------- waitlist */

function WaitlistList({
  entries,
  loading,
}: {
  entries: WaitlistEntry[];
  loading: boolean;
}) {
  const toast = useToast();
  const queryClient = useQueryClient();

  const leave = useMutation({
    mutationFn: (entryId: number) => leaveWaitlist(entryId),
    onSuccess: async () => {
      toast.success("Left the waitlist");
      await queryClient.invalidateQueries({ queryKey: ["waitlist"] });
    },
    onError: (error) => {
      const { title, detail } = describeError(error, "waitlist");
      toast.error(title, detail);
    },
  });

  if (loading) {
    return (
      <div className="space-y-3">
        {Array.from({ length: 2 }).map((_, index) => (
          <Skeleton key={index} className="h-24 w-full rounded-xl" />
        ))}
      </div>
    );
  }

  if (entries.length === 0) {
    return (
      <EmptyState
        title="Not waiting on anything"
        description="When a category sells out you can join its waitlist from the seat map. If someone cancels, you get first refusal."
      />
    );
  }

  return (
    <ul className="space-y-3">
      {entries.map((entry) => {
        const offered = entry.state === "offered" && entry.offer_expires_at;
        return (
          <li key={entry.id}>
            <Card
              className={cn(offered && "border-accent/30 bg-accent-soft")}
            >
              <div className="flex flex-wrap items-start justify-between gap-4 p-5">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <p className="font-display text-lg leading-tight text-text">
                      {entry.show.event_title}
                    </p>
                    {offered ? (
                      <Badge tone="accent">Seats offered</Badge>
                    ) : (
                      <Badge tone="neutral">Waiting</Badge>
                    )}
                  </div>
                  <p className="mt-1 text-[13px] text-muted">
                    {new Date(entry.show.starts_at).toLocaleString([], {
                      weekday: "short",
                      day: "numeric",
                      month: "short",
                      hour: "2-digit",
                      minute: "2-digit",
                    })}{" "}
                    &middot; {entry.show.venue_name}
                  </p>
                  <p className="mt-1 text-[13px] text-muted">
                    {entry.category_name} &middot; {entry.qty}{" "}
                    {entry.qty === 1 ? "seat" : "seats"}
                  </p>
                </div>

                <div className="shrink-0 text-right">
                  {offered ? (
                    <>
                      <p className="text-[11px] uppercase tracking-[0.12em] text-muted">
                        Claim within
                      </p>
                      <Countdown
                        expiresAt={entry.offer_expires_at!}
                        warnAtSeconds={120}
                        className="mt-0.5 text-xl"
                      />
                      <p className="mt-2 text-[12px] text-muted">
                        Check your email for the claim link.
                      </p>
                    </>
                  ) : (
                    <>
                      <p className="text-[11px] uppercase tracking-[0.12em] text-muted">
                        Position
                      </p>
                      <p className="font-display text-2xl tabular-nums text-accent">
                        {entry.position ?? "—"}
                      </p>
                      <Button
                        variant="quiet"
                        size="sm"
                        className="mt-1"
                        loading={leave.isPending && leave.variables === entry.id}
                        onClick={() => leave.mutate(entry.id)}
                      >
                        Leave
                      </Button>
                    </>
                  )}
                </div>
              </div>
            </Card>
          </li>
        );
      })}
    </ul>
  );
}

/* -------------------------------------------------------------- settings */

function Settings() {
  const { user, logout } = useAuth();
  return (
    <Card>
      <div className="space-y-4 p-5">
        <Field label="Name" value={user?.name ?? "—"} />
        <Field label="Email" value={user?.email ?? "—"} />
        <Field label="Account type" value={user?.role ?? "—"} />
        <Field
          label="Member since"
          value={
            user?.created_at
              ? new Date(user.created_at).toLocaleDateString([], {
                  day: "numeric",
                  month: "long",
                  year: "numeric",
                })
              : "—"
          }
        />
      </div>
      <div className="border-t border-border p-5">
        <Button variant="ghost" onClick={logout}>
          Sign out
        </Button>
      </div>
    </Card>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-4">
      <span className="text-[13px] text-muted">{label}</span>
      <span className="text-sm capitalize text-text">{value}</span>
    </div>
  );
}
