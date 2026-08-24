"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import {
  Popover,
  PopoverDivider,
  PopoverHeader,
  PopoverItem,
} from "@/components/ui/Popover";
import { useAuth } from "@/components/auth/AuthProvider";
import type { UserRole } from "@/lib/types";

const ROLE_LABEL: Record<UserRole, string> = {
  customer: "Customer",
  organiser: "Organiser",
  admin: "Venue admin",
};

/**
 * The account panel behind the avatar.
 *
 * Every destination is /profile with a tab, rather than four routes: the tabs
 * already exist and share one set of queries, so splitting them into pages
 * would refetch the same bookings four times and lose the counts in the tab
 * strip.
 *
 * Logged out, the avatar is not a menu at all -- it is a link to /login.
 * A menu whose only item is "sign in" is a menu that should have been a link.
 */
export function ProfileMenu() {
  const { user, logout } = useAuth();
  const router = useRouter();
  const [open, setOpen] = useState(false);

  const go = (tab: string) => {
    setOpen(false);
    router.push(tab === "upcoming" ? "/profile" : `/profile?tab=${tab}`);
  };

  const initials = (user?.name ?? "")
    .split(" ")
    .map((part) => part[0])
    .filter(Boolean)
    .slice(0, 2)
    .join("")
    .toUpperCase();

  if (!user) {
    return (
      <button
        type="button"
        onClick={() => router.push("/login")}
        aria-label="Sign in"
        className="grid h-9 w-9 place-items-center rounded-full border border-border bg-surface-2 text-muted transition-colors hover:border-border-strong hover:text-text"
      >
        <PersonIcon />
      </button>
    );
  }

  return (
    <Popover
      open={open}
      onClose={() => setOpen(false)}
      label="Account"
      className="w-60"
      trigger={(props) => (
        <button
          type="button"
          {...props}
          onClick={() => setOpen((value) => !value)}
          aria-label={`Account menu for ${user.name}`}
          className="grid h-9 w-9 place-items-center rounded-full border border-border bg-surface-2 text-[12px] font-semibold text-text transition-colors hover:border-border-strong"
        >
          {initials || <PersonIcon />}
        </button>
      )}
    >
      <PopoverHeader title={user.name} subtitle={ROLE_LABEL[user.role]} />
      <PopoverDivider />

      <div className="py-1">
        <PopoverItem onClick={() => go("upcoming")}>Upcoming Bookings</PopoverItem>
        <PopoverItem onClick={() => go("history")}>Booking History</PopoverItem>
        <PopoverItem onClick={() => go("waitlist")}>Waitlist</PopoverItem>
        <PopoverItem onClick={() => go("settings")}>Settings</PopoverItem>
      </div>

      <PopoverDivider />
      <div className="py-1">
        <PopoverItem
          onClick={() => {
            setOpen(false);
            logout();
          }}
        >
          Log out
        </PopoverItem>
      </div>
    </Popover>
  );
}

function PersonIcon() {
  return (
    <svg viewBox="0 0 16 16" className="h-4 w-4" aria-hidden="true">
      <circle cx="8" cy="5.5" r="2.75" fill="none" stroke="currentColor" strokeWidth="1.4" />
      <path
        d="M2.75 14c0-2.9 2.35-4.5 5.25-4.5s5.25 1.6 5.25 4.5"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
      />
    </svg>
  );
}
