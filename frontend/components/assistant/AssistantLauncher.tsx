"use client";

import { useEffect, useState } from "react";
import { AssistantPanel, SparkIcon } from "./AssistantPanel";
import { cn } from "@/lib/cn";

/**
 * The floating trigger.
 *
 * Bottom-right, and lifted clear of the sticky booking bar rather than
 * layered over it -- the seat map's selection bar is the thing someone is
 * mid-way through using, and covering the total or the Hold button with a
 * chat button would be the assistant getting in the way of the booking it
 * exists to help with.
 *
 * A spark, not a speech bubble: this finds and ranks things. A chat bubble
 * would promise a conversation partner, which sets up the "just book it"
 * expectation the assistant then has to decline.
 */
export function AssistantLauncher() {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open]);

  return (
    <div
      className={cn(
        "fixed right-4 z-50 flex flex-col items-end gap-3",
        // Clears the sticky selection bar on the seat map, which sits at
        // bottom-0 with p-4 and is about 5rem tall.
        "bottom-[calc(1rem+var(--assistant-offset,6.5rem))]",
        "sm:bottom-[calc(1rem+var(--assistant-offset,6.5rem))]",
      )}
    >
      {open && <AssistantPanel onClose={() => setOpen(false)} />}

      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-label={open ? "Close the assistant" : "Ask the assistant"}
        className={cn(
          "grid h-12 w-12 place-items-center rounded-full transition-all duration-200",
          "shadow-lg shadow-black/40",
          open
            ? "border border-border bg-surface-2 text-muted hover:text-text"
            : "bg-accent text-bg hover:bg-accent-hover active:translate-y-px",
        )}
      >
        {open ? (
          <svg viewBox="0 0 14 14" className="h-4 w-4" aria-hidden="true">
            <path
              d="M2 2l10 10M12 2L2 12"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
            />
          </svg>
        ) : (
          <SparkIcon className="h-5 w-5" />
        )}
      </button>
    </div>
  );
}
