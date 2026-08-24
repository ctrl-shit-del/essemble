"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Brand } from "./Brand";
import { useAuth } from "@/components/auth/AuthProvider";
import { cn } from "@/lib/cn";

/**
 * Organiser chrome.
 *
 * Deliberately NOT the customer nav with different links. This is a work
 * surface for someone who lives in it all day, so the whole posture changes:
 *
 *   - solid bar, not glass -- nothing is floating over artwork here
 *   - 56px tall against the customer's 64, tabs not pills, tighter tracking
 *   - a persistent secondary row for section context, so the operator always
 *     knows which slice of their catalogue they are editing
 *   - a full-width content well rather than the customer's centred column
 *
 * The customer shell is content-first with generous space. This one is
 * density-first: more rows visible without scrolling matters more than air.
 */

const TABS = [
  { href: "/organiser", label: "Overview", exact: true },
  { href: "/organiser/events", label: "Events" },
  { href: "/organiser/shows", label: "Shows" },
  { href: "/organiser/requests", label: "Venue Requests" },
  { href: "/organiser/insights", label: "Insights" },
];

export function OrganiserShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { user, logout } = useAuth();

  return (
    <div className="min-h-dvh bg-bg">
      <header className="sticky top-0 z-40 border-b border-border bg-surface">
        {/* Row 1: identity and account. Compact. */}
        <div className="mx-auto flex h-14 max-w-[1600px] items-center gap-6 px-6">
          <Brand suffix="ORGANISER" href="/organiser" compact />

          <nav aria-label="Organiser sections" className="ml-2 hidden lg:block">
            <ul className="flex items-center">
              {TABS.map((tab) => {
                const active = tab.exact
                  ? pathname === tab.href
                  : pathname?.startsWith(tab.href);
                return (
                  <li key={tab.href}>
                    <Link
                      href={tab.href}
                      className={cn(
                        "relative block px-3.5 py-4 text-[13px] tracking-tight transition-colors duration-150",
                        active ? "text-text" : "text-muted hover:text-text",
                      )}
                    >
                      {tab.label}
                      <span
                        aria-hidden="true"
                        className={cn(
                          "absolute inset-x-2 bottom-0 h-0.5 bg-accent transition-opacity duration-150",
                          active ? "opacity-100" : "opacity-0",
                        )}
                      />
                    </Link>
                  </li>
                );
              })}
            </ul>
          </nav>

          <div className="ml-auto flex items-center gap-3">
            <span className="hidden text-[13px] text-muted sm:inline">
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

        {/* Row 2: mobile tab strip, scrollable rather than collapsed into a
            menu -- an operator switching sections repeatedly should not have
            to open something first. */}
        <div className="border-t border-border lg:hidden">
          <ul className="mx-auto flex max-w-[1600px] gap-1 overflow-x-auto px-4 py-2">
            {TABS.map((tab) => {
              const active = tab.exact
                ? pathname === tab.href
                : pathname?.startsWith(tab.href);
              return (
                <li key={tab.href}>
                  <Link
                    href={tab.href}
                    className={cn(
                      "block whitespace-nowrap rounded-md px-3 py-1.5 text-[13px] transition-colors",
                      active
                        ? "bg-accent-soft text-accent"
                        : "text-muted hover:bg-surface-2 hover:text-text",
                    )}
                  >
                    {tab.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      </header>

      {/* Wide well, tight gutters: tables and schedule grids want the width. */}
      <main className="mx-auto max-w-[1600px] px-6 py-6">{children}</main>
    </div>
  );
}
