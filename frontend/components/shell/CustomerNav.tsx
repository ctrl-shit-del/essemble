"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Brand } from "./Brand";
import { NotificationsMenu } from "./NotificationsMenu";
import { ProfileMenu } from "./ProfileMenu";
import { cn } from "@/lib/cn";

const LINKS = [
  { href: "/", label: "Now Showing" },
  { href: "/events", label: "Events" },
  { href: "/bookings", label: "My Bookings" },
  { href: "/waitlist", label: "Waitlist" },
];

/**
 * Customer chrome: glass top nav, brand left, links centre, tools right.
 *
 * THE SEARCH INTERACTION
 * Opening search collapses the centre links toward the brand while the field
 * expands into the space they vacate. Done with CSS transitions only -- the
 * links animate max-width/opacity to zero and the field animates its width
 * up, so the two movements are a single continuous exchange rather than one
 * element replacing another. Closing plays it in reverse.
 *
 * Width and opacity are used rather than a layout switch because both are
 * cheap to animate and neither reflows the rest of the bar mid-transition.
 */
export function CustomerNav() {
  const pathname = usePathname();
  const [searchOpen, setSearchOpen] = useState(false);
  const [query, setQuery] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (searchOpen) inputRef.current?.focus();
  }, [searchOpen]);

  useEffect(() => {
    if (!searchOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setSearchOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [searchOpen]);

  return (
    <header className="glass sticky top-0 z-40 border-x-0 border-t-0">
      <div className="mx-auto flex h-16 max-w-7xl items-center gap-4 px-6">
        {/* Brand: the anchor the links collapse toward. */}
        <Brand className="shrink-0" />

        {/* Centre links. Collapse to zero width when search opens. */}
        <nav
          aria-label="Primary"
          className={cn(
            "hidden flex-1 justify-center md:flex",
            "overflow-hidden transition-[max-width,opacity,transform] duration-300",
            "[transition-timing-function:var(--ease-out-soft)]",
            searchOpen
              ? "pointer-events-none max-w-0 -translate-x-4 opacity-0"
              : "max-w-2xl translate-x-0 opacity-100",
          )}
          // Hidden from assistive tech while collapsed, so the links are not
          // reachable by a screen reader when they are invisible.
          aria-hidden={searchOpen}
        >
          <ul className="flex items-center gap-1 whitespace-nowrap">
            {LINKS.map((link) => {
              const active =
                link.href === "/"
                  ? pathname === "/"
                  : pathname?.startsWith(link.href);
              return (
                <li key={link.href}>
                  <Link
                    href={link.href}
                    tabIndex={searchOpen ? -1 : undefined}
                    className={cn(
                      "relative rounded-lg px-3 py-2 text-sm transition-colors duration-150",
                      active ? "text-text" : "text-muted hover:text-text",
                    )}
                  >
                    {link.label}
                    {/* Amber underline is the only active-state colour. */}
                    <span
                      aria-hidden="true"
                      className={cn(
                        "absolute inset-x-3 -bottom-0.5 h-px origin-left bg-accent",
                        "transition-transform duration-200",
                        active ? "scale-x-100" : "scale-x-0",
                      )}
                    />
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>

        {/* Tools. The field grows into the space the links gave up. */}
        <div className="ml-auto flex items-center gap-1.5">
          <div
            className={cn(
              "flex items-center overflow-hidden rounded-full border transition-[width,background-color,border-color] duration-300",
              "[transition-timing-function:var(--ease-out-soft)]",
              searchOpen
                ? "w-[min(30rem,52vw)] border-border-strong bg-surface"
                : "w-10 border-transparent bg-transparent",
            )}
          >
            <button
              type="button"
              onClick={() => setSearchOpen((open) => !open)}
              aria-label={searchOpen ? "Close search" : "Search"}
              aria-expanded={searchOpen}
              className="grid h-10 w-10 shrink-0 place-items-center rounded-full text-muted transition-colors hover:text-text"
            >
              <SearchIcon />
            </button>

            <input
              ref={inputRef}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search films, events, venues"
              tabIndex={searchOpen ? undefined : -1}
              aria-hidden={!searchOpen}
              className={cn(
                "h-10 min-w-0 flex-1 bg-transparent pr-3 text-sm text-text outline-none",
                "placeholder:text-muted/60",
                !searchOpen && "pointer-events-none",
              )}
            />

            {searchOpen && query && (
              <button
                type="button"
                onClick={() => setQuery("")}
                aria-label="Clear search"
                className="mr-1 grid h-7 w-7 shrink-0 place-items-center rounded-full text-muted hover:text-text"
              >
                <CloseIcon />
              </button>
            )}
          </div>

          {/* These step aside as the field grows, rather than being covered. */}
          <div
            className={cn(
              "flex items-center gap-1.5 overflow-hidden transition-[max-width,opacity] duration-300",
              "[transition-timing-function:var(--ease-out-soft)]",
              searchOpen ? "max-w-0 opacity-0" : "max-w-xs opacity-100",
            )}
            aria-hidden={searchOpen}
          >
            <button
              type="button"
              className="hidden items-center gap-1.5 whitespace-nowrap rounded-lg px-2.5 py-2 text-sm text-muted transition-colors hover:text-text sm:inline-flex"
              tabIndex={searchOpen ? -1 : undefined}
            >
              <PinIcon />
              Chennai
            </button>

            <NotificationsMenu />
            <ProfileMenu />
          </div>
        </div>
      </div>
    </header>
  );
}

function SearchIcon() {
  return (
    <svg viewBox="0 0 16 16" className="h-[18px] w-[18px]" aria-hidden="true">
      <circle
        cx="7"
        cy="7"
        r="4.5"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
      />
      <path
        d="M10.5 10.5L14 14"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
    </svg>
  );
}

function CloseIcon() {
  return (
    <svg viewBox="0 0 12 12" className="h-3 w-3" aria-hidden="true">
      <path
        d="M2 2l8 8M10 2L2 10"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
    </svg>
  );
}

function PinIcon() {
  return (
    <svg viewBox="0 0 16 16" className="h-4 w-4" aria-hidden="true">
      <path
        d="M8 14s4.5-4.2 4.5-7.5a4.5 4.5 0 1 0-9 0C3.5 9.8 8 14 8 14z"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.4"
      />
      <circle cx="8" cy="6.5" r="1.6" fill="currentColor" />
    </svg>
  );
}
