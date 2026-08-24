"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { cn } from "@/lib/cn";

/**
 * Time remaining against a server deadline.
 *
 * THE RULE: this recomputes `expiresAt - now` on every tick. It never starts
 * a local timer from a duration and counts it down.
 *
 * That distinction is the whole point. A decrementing local counter desyncs
 * three ways, and every one of them ends with the UI promising time on a hold
 * the server has already released:
 *
 *   - refresh:   a fresh counter restarts from the full duration
 *   - tab sleep: background tabs are throttled, so the interval fires fewer
 *                times than seconds actually elapsed and the clock runs slow
 *   - skew:      the client clock may differ from the server's
 *
 * The first two are fixed by deriving from the absolute deadline. The third
 * is fixed by `serverNowIso`: pass the server's own timestamp from the same
 * response as `expiresAt` and the offset between the two clocks is corrected
 * once, rather than being baked into every tick.
 */

export type CountdownProps = {
  /** ISO 8601 deadline from the server, e.g. hold.expires_at. */
  expiresAt: string;
  /**
   * The server's clock at the moment `expiresAt` was issued. When supplied,
   * remaining time is measured on the server's timeline rather than this
   * machine's.
   */
  serverNowIso?: string;
  onExpire?: () => void;
  /** Seconds below which the display turns urgent. */
  warnAtSeconds?: number;
  className?: string;
  /** "mm:ss" for a booking bar, "compact" for inline copy. */
  format?: "clock" | "compact";
  label?: string;
};

function useClockSkewMs(serverNowIso?: string): number {
  // Captured once. Re-measuring on every render would let a slow response
  // ratchet the correction in one direction.
  return useMemo(() => {
    if (!serverNowIso) return 0;
    const serverNow = Date.parse(serverNowIso);
    if (Number.isNaN(serverNow)) return 0;
    return serverNow - Date.now();
  }, [serverNowIso]);
}

export function useRemainingSeconds(
  expiresAt: string,
  serverNowIso?: string,
  onExpire?: () => void,
): number {
  const skewMs = useClockSkewMs(serverNowIso);
  const deadline = useMemo(() => Date.parse(expiresAt), [expiresAt]);

  const compute = useMemo(
    () => () => {
      if (Number.isNaN(deadline)) return 0;
      // Always derived from the absolute deadline; never accumulated.
      return Math.max(0, Math.ceil((deadline - (Date.now() + skewMs)) / 1000));
    },
    [deadline, skewMs],
  );

  const [remaining, setRemaining] = useState(compute);

  // Kept in a ref so a caller passing an inline arrow does not restart the
  // interval on every render.
  const onExpireRef = useRef(onExpire);
  useEffect(() => {
    onExpireRef.current = onExpire;
  }, [onExpire]);

  const firedRef = useRef(false);

  useEffect(() => {
    firedRef.current = false;
    setRemaining(compute());

    const tick = () => {
      const next = compute();
      setRemaining(next);
      if (next === 0 && !firedRef.current) {
        firedRef.current = true;
        onExpireRef.current?.();
      }
    };

    const interval = setInterval(tick, 1000);

    // A throttled background tab fires the interval far less often than once
    // a second. Recomputing on wake means the number is correct the instant
    // the tab is looked at, rather than catching up one second per second.
    const onVisibility = () => {
      if (document.visibilityState === "visible") tick();
    };
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("focus", tick);

    return () => {
      clearInterval(interval);
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("focus", tick);
    };
  }, [compute]);

  return remaining;
}

export function formatRemaining(
  seconds: number,
  format: "clock" | "compact" = "clock",
): string {
  if (seconds <= 0) return format === "clock" ? "00:00" : "expired";

  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const secs = seconds % 60;

  if (format === "compact") {
    if (hours > 0) return `${hours}h ${minutes}m`;
    if (minutes > 0) return `${minutes}m ${secs}s`;
    return `${secs}s`;
  }

  const mm = String(hours > 0 ? minutes : minutes).padStart(2, "0");
  const ss = String(secs).padStart(2, "0");
  return hours > 0 ? `${hours}:${mm}:${ss}` : `${mm}:${ss}`;
}

export function Countdown({
  expiresAt,
  serverNowIso,
  onExpire,
  warnAtSeconds = 60,
  className,
  format = "clock",
  label,
}: CountdownProps) {
  const remaining = useRemainingSeconds(expiresAt, serverNowIso, onExpire);
  const expired = remaining <= 0;
  const urgent = !expired && remaining <= warnAtSeconds;

  return (
    <span
      className={cn("inline-flex items-baseline gap-1.5", className)}
      // Announce the minute, not every second -- a per-second live region is
      // unusable with a screen reader.
      aria-live={urgent ? "assertive" : "off"}
    >
      {label && <span className="text-[13px] text-muted">{label}</span>}
      <span
        className={cn(
          "font-display tabular-nums tracking-tight",
          expired && "text-danger",
          urgent && "text-accent",
          !expired && !urgent && "text-text",
          urgent && "animate-[essemble-pulse-soft_1.6s_ease-in-out_infinite]",
        )}
      >
        {formatRemaining(remaining, format)}
      </span>
      <span className="sr-only">
        {expired ? "Expired" : `${remaining} seconds remaining`}
      </span>
    </span>
  );
}
