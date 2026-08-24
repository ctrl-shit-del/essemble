"use client";

import { useRouter } from "next/navigation";
import { formatMoney } from "@/lib/seatmap";
import type { AssistantOption, SeatOption, ShowOption } from "@/lib/assistant";
import { cn } from "@/lib/cn";

/**
 * Options as cards, never as text.
 *
 * The assistant's prose says what it found and why; these carry the facts and
 * the tap target. Dumping the same information into the reply would make the
 * model responsible for rendering data it was handed, which is exactly where
 * a number gets quietly changed in transcription.
 *
 * BOTH card types HAND OFF. Neither books. A show card opens the seat map; a
 * seat card opens the seat map with those seats pre-selected. Selection is
 * client state -- the customer still presses Hold themselves.
 */
export function OptionCards({ options }: { options: AssistantOption[] }) {
  if (options.length === 0) return null;

  return (
    <ul className="mt-3 space-y-2">
      {options.map((option, index) => (
        <li key={`${option.kind}-${index}`}>
          {option.kind === "show" ? (
            <ShowCard option={option} />
          ) : (
            <SeatCard option={option} />
          )}
        </li>
      ))}
    </ul>
  );
}

function ShowCard({ option }: { option: ShowOption }) {
  const router = useRouter();
  const starts = new Date(option.starts_at);

  return (
    <button
      type="button"
      onClick={() => router.push(`/shows/${option.show_id}/seats`)}
      className={cn(
        "w-full rounded-xl border border-border bg-surface p-3.5 text-left",
        "transition-colors duration-150 hover:border-accent hover:bg-surface-2",
      )}
    >
      <p className="font-display text-[15px] leading-tight text-text">
        {option.title}
      </p>
      <p className="mt-1 text-[12px] text-muted">
        {option.venue} &middot; {option.screen}
        {option.city ? ` · ${option.city}` : ""}
      </p>
      <div className="mt-2 flex flex-wrap items-baseline justify-between gap-2">
        <span className="text-[13px] text-text tabular-nums">
          {starts.toLocaleString([], {
            weekday: "short",
            day: "numeric",
            month: "short",
            hour: "2-digit",
            minute: "2-digit",
          })}
        </span>
        <span className="text-[12px] text-muted">
          {option.from_price && (
            <span className="text-accent">
              from {formatMoney(Number(option.from_price))}
            </span>
          )}
          {" · "}
          {option.seats_available} free
        </span>
      </div>
    </button>
  );
}

function SeatCard({ option }: { option: SeatOption }) {
  const router = useRouter();

  return (
    <button
      type="button"
      onClick={() =>
        // Pre-SELECT, never pre-hold. The seat map reads these into its own
        // client-side selection state and the hold button stays untouched.
        router.push(
          `/shows/${option.show_id}/seats?seats=${option.seat_ids.join(",")}`,
        )
      }
      className={cn(
        "w-full rounded-xl border border-accent/25 bg-accent-soft p-3.5 text-left",
        "transition-colors duration-150 hover:border-accent",
      )}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="font-display text-[15px] leading-tight text-text">
          {option.seats.join(", ")}
        </p>
        <p className="font-display text-[15px] text-accent tabular-nums">
          {formatMoney(Number(option.total))}
        </p>
      </div>
      <p className="mt-1 text-[12px] text-muted">
        {option.category} &middot; {formatMoney(Number(option.price_per_seat))} each
      </p>
      {/* Built server-side from the score breakdown, so the justification is
          arithmetic rather than something the model felt like saying. */}
      <p className="mt-2 text-[12px] leading-relaxed text-text/80">
        {option.reason}
      </p>
    </button>
  );
}
