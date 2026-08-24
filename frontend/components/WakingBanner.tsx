"use client";

import { useEffect, useState } from "react";
import { getWakeState, subscribeWake, type WakeState } from "@/lib/wake-store";
import { cn } from "@/lib/cn";

/**
 * "Waking the server."
 *
 * The API sleeps after ~15 minutes idle and the next request pays a cold
 * start of up to a minute. Without this the first visit looks broken: a
 * spinner that never resolves. Saying what is happening turns a bug into a
 * wait, which people will sit through.
 *
 * Stays up briefly after the first response lands, so it reads as resolved
 * rather than as a flicker nobody had time to read.
 */
export function WakingBanner() {
  const [state, setState] = useState<WakeState>("idle");
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    setState(getWakeState());
    return subscribeWake(setState);
  }, []);

  useEffect(() => {
    if (state === "waking") {
      setVisible(true);
      return;
    }
    if (state === "awake") {
      const timer = setTimeout(() => setVisible(false), 1600);
      return () => clearTimeout(timer);
    }
    setVisible(false);
  }, [state]);

  if (!visible) return null;
  const awake = state === "awake";

  return (
    <div
      role="status"
      aria-live="polite"
      className={cn(
        "fixed inset-x-0 top-0 z-[70] flex justify-center px-4 pt-3",
        "pointer-events-none",
      )}
    >
      <div
        className={cn(
          "glass pointer-events-auto flex items-center gap-3 rounded-full py-2 pl-3 pr-4",
          "animate-[essemble-fade-in_200ms_var(--ease-out-soft)]",
          awake && "border-success/30",
        )}
      >
        {awake ? (
          <svg viewBox="0 0 16 16" className="h-4 w-4 text-success" aria-hidden="true">
            <path
              d="M3.5 8.5l3 3 6-6.5"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        ) : (
          <span className="relative flex h-4 w-4 items-center justify-center">
            <span className="absolute h-2 w-2 rounded-full bg-accent animate-[essemble-pulse-soft_1.4s_ease-in-out_infinite]" />
          </span>
        )}
        <p className="text-[13px] text-text">
          {awake ? (
            "Server is awake."
          ) : (
            <>
              Waking the server
              <span className="text-muted">
                {" "}
                &mdash; free tier, this can take up to a minute
              </span>
            </>
          )}
        </p>
      </div>
    </div>
  );
}
