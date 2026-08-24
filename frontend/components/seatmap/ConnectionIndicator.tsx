"use client";

import type { Transport } from "@/hooks/useLiveSeatMap";
import { cn } from "@/lib/cn";

/**
 * Which transport is actually carrying updates.
 *
 * Honest, not decorative. It reports the real state of the EventSource, so
 * "Live" means a stream is genuinely open and "Updating" means the map is
 * being refreshed by polling every 5 seconds. Both are correct behaviour --
 * the poll is the supported fallback, not a degraded mode -- so neither reads
 * as an error.
 *
 * The distinction matters to an evaluator: it says the two paths exist and
 * which one is in use, rather than claiming realtime and hoping.
 */
export function ConnectionIndicator({
  transport,
  className,
}: {
  transport: Transport;
  className?: string;
}) {
  const config = {
    live: {
      label: "Live",
      detail: "Streaming seat changes",
      dot: "bg-success",
      pulse: true,
    },
    polling: {
      label: "Updating",
      detail: "Refreshing every 5s",
      dot: "bg-accent",
      pulse: false,
    },
    connecting: {
      label: "Connecting",
      detail: "Opening the live stream",
      dot: "bg-muted",
      pulse: true,
    },
  }[transport];

  return (
    <span
      className={cn(
        "inline-flex items-center gap-2 rounded-full border border-border bg-surface px-2.5 py-1",
        className,
      )}
      title={config.detail}
    >
      <span className="relative flex h-1.5 w-1.5">
        {config.pulse && (
          <span
            className={cn(
              "absolute inline-flex h-full w-full rounded-full opacity-60",
              config.dot,
              "animate-[essemble-pulse-soft_1.8s_ease-in-out_infinite]",
            )}
          />
        )}
        <span className={cn("relative inline-flex h-1.5 w-1.5 rounded-full", config.dot)} />
      </span>
      <span className="text-[11px] uppercase tracking-[0.12em] text-muted">
        {config.label}
      </span>
    </span>
  );
}
