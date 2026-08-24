"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Popover, PopoverDivider } from "@/components/ui/Popover";
import { Countdown } from "@/components/ui/Countdown";
import { useAuth } from "@/components/auth/AuthProvider";
import { fetchWaitlist } from "@/lib/bookings";
import { cn } from "@/lib/cn";

/**
 * The bell, made honest.
 *
 * There is no notifications API and inventing one would mean inventing a
 * table, so this reads the only thing the backend actually has to tell
 * someone about: GET /api/waitlist, which already returns queue position and
 * offer expiry. A live offer is genuinely the one time-critical thing a
 * customer can be notified of -- it lapses, and when it does the seats go to
 * the next person.
 *
 * The dot only appears when there is a live offer. A permanently-lit
 * indicator is the same as no indicator, since nobody looks twice at
 * something that is always on.
 */
export function NotificationsMenu() {
  const { user } = useAuth();
  const router = useRouter();
  const [open, setOpen] = useState(false);

  const query = useQuery({
    queryKey: ["waitlist"],
    queryFn: fetchWaitlist,
    enabled: Boolean(user),
    // An offer is time-limited, so a stale copy is actively misleading.
    staleTime: 15_000,
    refetchInterval: open ? 15_000 : 60_000,
  });

  const entries = (query.data ?? []).filter(
    (entry) => entry.state === "waiting" || entry.state === "offered",
  );
  const offers = entries.filter(
    (entry) => entry.state === "offered" && entry.offer_expires_at,
  );

  if (!user) return null;

  return (
    <Popover
      open={open}
      onClose={() => setOpen(false)}
      label="Notifications"
      className="w-80"
      trigger={(props) => (
        <button
          type="button"
          {...props}
          onClick={() => setOpen((value) => !value)}
          aria-label={
            offers.length > 0
              ? `Notifications, ${offers.length} ${
                  offers.length === 1 ? "offer" : "offers"
                } waiting for you`
              : "Notifications"
          }
          className="relative grid h-10 w-10 place-items-center rounded-full text-muted transition-colors hover:text-text"
        >
          <BellIcon />
          {offers.length > 0 && (
            <span
              aria-hidden="true"
              className="absolute right-2.5 top-2.5 h-1.5 w-1.5 rounded-full bg-accent"
            />
          )}
        </button>
      )}
    >
      <div className="px-3.5 py-3">
        <p className="text-[11px] uppercase tracking-[0.12em] text-muted">
          Waitlist
        </p>
      </div>
      <PopoverDivider />

      {query.isLoading ? (
        <p className="px-3.5 py-6 text-center text-[13px] text-muted">Loading…</p>
      ) : entries.length === 0 ? (
        <div className="px-3.5 py-6 text-center">
          <p className="text-[13px] text-text">Nothing waiting</p>
          <p className="mt-1 text-[12px] leading-relaxed text-muted">
            Join a waitlist on a sold-out category and you will be told here
            when seats free up.
          </p>
        </div>
      ) : (
        <ul className="max-h-80 overflow-y-auto py-1">
          {entries.map((entry) => {
            const offered = entry.state === "offered" && entry.offer_expires_at;
            return (
              <li key={entry.id}>
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => {
                    setOpen(false);
                    router.push("/profile?tab=waitlist");
                  }}
                  className={cn(
                    "w-full px-3.5 py-2.5 text-left transition-colors hover:bg-surface-2",
                    offered && "bg-accent-soft",
                  )}
                >
                  <p className="truncate text-[13px] text-text">
                    {entry.show.event_title}
                  </p>
                  <p className="mt-0.5 truncate text-[12px] text-muted">
                    {entry.category_name} &middot; {entry.qty}{" "}
                    {entry.qty === 1 ? "seat" : "seats"}
                  </p>

                  {offered ? (
                    <span className="mt-1.5 flex items-baseline gap-2">
                      <span className="text-[11px] uppercase tracking-[0.1em] text-accent">
                        Seats offered
                      </span>
                      <Countdown
                        expiresAt={entry.offer_expires_at!}
                        warnAtSeconds={120}
                        format="compact"
                        className="text-[12px]"
                      />
                    </span>
                  ) : (
                    <span className="mt-1 block text-[12px] text-muted">
                      Position {entry.position ?? "—"}
                    </span>
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      )}

      <PopoverDivider />
      <div className="py-1">
        <button
          type="button"
          role="menuitem"
          onClick={() => {
            setOpen(false);
            router.push("/profile?tab=waitlist");
          }}
          className="w-full px-3.5 py-2.5 text-left text-[13px] text-muted transition-colors hover:bg-surface-2 hover:text-text"
        >
          Open your waitlist
        </button>
      </div>
    </Popover>
  );
}

function BellIcon() {
  return (
    <svg viewBox="0 0 16 16" className="h-[18px] w-[18px]" aria-hidden="true">
      <path
        d="M4 6.5a4 4 0 1 1 8 0c0 3 1 4 1 4H3s1-1 1-4z"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinejoin="round"
      />
      <path
        d="M6.5 13a1.5 1.5 0 0 0 3 0"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
      />
    </svg>
  );
}
