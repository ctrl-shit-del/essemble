"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Brand } from "./Brand";
import { useAuth } from "@/components/auth/AuthProvider";
import { cn } from "@/lib/cn";

/**
 * Admin chrome.
 *
 * The third distinct posture, not a third link list. An admin's work is
 * always scoped to ONE venue -- screens, layouts, requests and door check-in
 * all belong to a venue -- and acting on the wrong one is the expensive
 * mistake here (regenerating a layout, approving someone else's slot).
 *
 * So the venue is not a page you navigate to, it is a control in the header
 * that scopes everything beneath it, and the navigation is hierarchical:
 * venue-scoped sections in a rail, account-level items separated out. That
 * is why this is a sidebar while organiser is a tab bar -- a rail can show
 * two levels at once; a horizontal strip cannot.
 */

const VENUE_SECTIONS = [
  { href: "/admin", label: "Overview", exact: true },
  { href: "/admin/screens", label: "Screens & Layouts" },
  { href: "/admin/requests", label: "Slot Requests", badge: true },
  { href: "/admin/scanner", label: "Scanner" },
  { href: "/admin/checkin", label: "Door Check-in" },
];

const ACCOUNT_SECTIONS = [{ href: "/admin/venues", label: "All Venues" }];

// Placeholder until the venue list is wired up in a later pass.
const VENUES = [
  { id: 1, name: "PVR Marina", city: "Chennai" },
  { id: 2, name: "Luxe Cinemas", city: "Chennai" },
];

export function AdminShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { user, logout } = useAuth();
  const [venueId, setVenueId] = useState(VENUES[0].id);
  const venue = VENUES.find((item) => item.id === venueId) ?? VENUES[0];

  return (
    <div className="min-h-dvh bg-bg">
      {/* Header carries the venue context: it scopes every section below. */}
      <header className="sticky top-0 z-40 border-b border-border bg-surface">
        <div className="flex h-14 items-center gap-4 px-5">
          <Brand suffix="ADMIN" href="/admin" compact />

          <div
            aria-hidden="true"
            className="hidden h-5 w-px bg-border sm:block"
          />

          {/* The scope control. Deliberately prominent -- every destructive
              action on the pages below is relative to this value. */}
          <label className="hidden items-center gap-2 sm:flex">
            <span className="text-[11px] uppercase tracking-[0.14em] text-muted">
              Venue
            </span>
            <div className="relative">
              <select
                value={venueId}
                onChange={(event) => setVenueId(Number(event.target.value))}
                className="appearance-none rounded-md border border-border bg-surface-2 py-1.5 pl-3 pr-8 text-[13px] text-text transition-colors hover:border-border-strong focus:border-accent focus:outline-none"
              >
                {VENUES.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name} &middot; {item.city}
                  </option>
                ))}
              </select>
              <svg
                viewBox="0 0 12 12"
                aria-hidden="true"
                className="pointer-events-none absolute right-2.5 top-1/2 h-3 w-3 -translate-y-1/2 text-muted"
              >
                <path
                  d="M2.5 4.5 6 8l3.5-3.5"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </div>
          </label>

          <div className="ml-auto flex items-center gap-3">
            <span className="hidden text-[13px] text-muted md:inline">
              {user?.name}
            </span>
            <button
              type="button"
              onClick={logout}
              className="rounded-md border border-border px-2.5 py-1.5 text-[12px] text-muted transition-colors hover:border-border-strong hover:text-text"
            >
              Sign out
            </button>
          </div>
        </div>
      </header>

      <div className="flex">
        {/* Hierarchical rail: venue-scoped above, account-level below. */}
        <aside className="sticky top-14 hidden h-[calc(100dvh-3.5rem)] w-60 shrink-0 border-r border-border bg-surface px-3 py-5 lg:block">
          <p className="px-3 pb-2 text-[10px] uppercase tracking-[0.16em] text-muted">
            {venue.name}
          </p>
          <SectionList sections={VENUE_SECTIONS} pathname={pathname} />

          <div className="my-5 h-px bg-border" />

          <p className="px-3 pb-2 text-[10px] uppercase tracking-[0.16em] text-muted">
            Account
          </p>
          <SectionList sections={ACCOUNT_SECTIONS} pathname={pathname} />
        </aside>

        <main className="min-w-0 flex-1 px-5 py-6 lg:px-8">
          {/* Small screens lose the rail, so the scope has to be restated. */}
          <p className="mb-4 text-[11px] uppercase tracking-[0.16em] text-muted lg:hidden">
            {venue.name} &middot; {venue.city}
          </p>
          {children}
        </main>
      </div>
    </div>
  );
}

function SectionList({
  sections,
  pathname,
}: {
  sections: { href: string; label: string; exact?: boolean; badge?: boolean }[];
  pathname: string | null;
}) {
  return (
    <nav>
      <ul className="space-y-0.5">
        {sections.map((section) => {
          const active = section.exact
            ? pathname === section.href
            : pathname?.startsWith(section.href);
          return (
            <li key={section.href}>
              <Link
                href={section.href}
                className={cn(
                  "flex items-center justify-between rounded-lg px-3 py-2 text-[13px] transition-colors duration-150",
                  active
                    ? "bg-surface-2 text-text"
                    : "text-muted hover:bg-surface-2 hover:text-text",
                )}
              >
                <span className="flex items-center gap-2">
                  <span
                    aria-hidden="true"
                    className={cn(
                      "h-3.5 w-0.5 rounded-full transition-colors",
                      active ? "bg-accent" : "bg-transparent",
                    )}
                  />
                  {section.label}
                </span>
                {section.badge && (
                  <span className="rounded-full bg-accent-soft px-1.5 py-0.5 text-[10px] font-semibold text-accent">
                    1
                  </span>
                )}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
