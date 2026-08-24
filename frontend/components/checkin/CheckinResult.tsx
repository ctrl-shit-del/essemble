"use client";

import type { CheckinOutcome } from "@/lib/checkin";
import { cn } from "@/lib/cn";

/**
 * The verdict, as seen at a door.
 *
 * Designed to be GLANCED at: a phone held at arm's length, in a dark foyer,
 * by someone with a queue behind them. So the colour and the single word do
 * the work, the detail sits underneath for the one time in fifty it is
 * actually read, and nothing requires scrolling to reach a decision.
 *
 * Colour is not the only channel -- each state carries a distinct glyph and
 * its own word, so it survives a colour-blind reader and a bad screen.
 */
export function CheckinResult({
  outcome,
  compact = false,
}: {
  outcome: CheckinOutcome;
  compact?: boolean;
}) {
  if (outcome.kind === "valid") {
    const ticket = outcome.ticket;
    return (
      <Panel tone="valid" word="Admit" glyph={<Tick />} compact={compact}>
        <p
          className={cn(
            "font-display leading-tight text-text",
            compact ? "text-xl" : "text-3xl",
          )}
        >
          {ticket.event_title}
        </p>
        <p className="mt-1 text-[15px] text-muted">
          {ticket.venue_name} &middot; {ticket.screen_name}
        </p>

        <dl
          className={cn(
            "mt-5 grid gap-x-6 gap-y-3",
            compact ? "grid-cols-2" : "grid-cols-2 sm:grid-cols-3",
          )}
        >
          <Field label="Seats" emphasis>
            {ticket.seats.join(", ")}
          </Field>
          <Field label="Name">{ticket.customer_name}</Field>
          <Field label="Reference">{ticket.reference}</Field>
          <Field label="Showtime">
            {new Date(ticket.starts_at).toLocaleString([], {
              weekday: "short",
              day: "numeric",
              month: "short",
              hour: "2-digit",
              minute: "2-digit",
            })}
          </Field>
        </dl>
      </Panel>
    );
  }

  if (outcome.kind === "used") {
    return (
      <Panel tone="used" word="Already used" glyph={<Warning />} compact={compact}>
        <p className="text-[15px] leading-relaxed text-text">
          This ticket was scanned earlier. Do not admit again without checking
          with a supervisor.
        </p>
        {outcome.checkedInAt && (
          <div className="mt-5">
            <p className="text-[11px] uppercase tracking-[0.14em] text-muted">
              Admitted at
            </p>
            <p
              className={cn(
                "mt-1 font-display tabular-nums text-text",
                compact ? "text-2xl" : "text-4xl",
              )}
            >
              {new Date(outcome.checkedInAt).toLocaleTimeString([], {
                hour: "2-digit",
                minute: "2-digit",
                second: "2-digit",
              })}
            </p>
            <p className="mt-0.5 text-[13px] text-muted">
              {new Date(outcome.checkedInAt).toLocaleDateString([], {
                weekday: "long",
                day: "numeric",
                month: "long",
              })}
            </p>
          </div>
        )}
        {outcome.reference && (
          <p className="mt-4 text-[13px] text-muted">
            Reference <span className="text-text">{outcome.reference}</span>
          </p>
        )}
      </Panel>
    );
  }

  return (
    <Panel tone="invalid" word="Do not admit" glyph={<Cross />} compact={compact}>
      <p className="text-[15px] leading-relaxed text-text">
        This ticket is not valid for this door.
      </p>
      <p className="mt-2 text-[13px] leading-relaxed text-muted">
        It may be for another venue, already cancelled, or not a genuine
        ticket. Send the holder to the box office.
      </p>
      {outcome.reference && (
        <p className="mt-4 text-[13px] text-muted">
          Reference <span className="text-text">{outcome.reference}</span>
        </p>
      )}
    </Panel>
  );
}

/* ----------------------------------------------------------------- panel */

const TONES = {
  valid: {
    border: "border-success/40",
    bg: "bg-success-soft",
    text: "text-success",
  },
  used: {
    border: "border-accent/40",
    bg: "bg-accent-soft",
    text: "text-accent",
  },
  invalid: {
    border: "border-danger/40",
    bg: "bg-danger-soft",
    text: "text-danger",
  },
} as const;

function Panel({
  tone,
  word,
  glyph,
  compact,
  children,
}: {
  tone: keyof typeof TONES;
  word: string;
  glyph: React.ReactNode;
  compact: boolean;
  children: React.ReactNode;
}) {
  const style = TONES[tone];
  return (
    <section
      role="status"
      aria-live="assertive"
      className={cn("rounded-2xl border", style.border, style.bg)}
    >
      <div
        className={cn(
          "flex items-center gap-3 border-b px-6",
          style.border,
          compact ? "py-4" : "py-6",
        )}
      >
        <span className={cn("shrink-0", style.text)}>{glyph}</span>
        <p
          className={cn(
            "font-display font-semibold uppercase tracking-[0.06em]",
            style.text,
            compact ? "text-2xl" : "text-4xl",
          )}
        >
          {word}
        </p>
      </div>
      <div className={cn("px-6", compact ? "py-5" : "py-7")}>{children}</div>
    </section>
  );
}

function Field({
  label,
  children,
  emphasis = false,
}: {
  label: string;
  children: React.ReactNode;
  emphasis?: boolean;
}) {
  return (
    <div>
      <dt className="text-[11px] uppercase tracking-[0.14em] text-muted">
        {label}
      </dt>
      <dd
        className={cn(
          "mt-1 text-text",
          emphasis ? "font-display text-2xl leading-none" : "text-[15px]",
        )}
      >
        {children}
      </dd>
    </div>
  );
}

/* ----------------------------------------------------------------- glyphs */

function Tick() {
  return (
    <svg viewBox="0 0 32 32" className="h-9 w-9" aria-hidden="true">
      <circle cx="16" cy="16" r="14" fill="none" stroke="currentColor" strokeWidth="2.5" />
      <path
        d="M9.5 16.5l4.5 4.5 9-10"
        fill="none"
        stroke="currentColor"
        strokeWidth="3"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function Warning() {
  return (
    <svg viewBox="0 0 32 32" className="h-9 w-9" aria-hidden="true">
      <circle cx="16" cy="16" r="14" fill="none" stroke="currentColor" strokeWidth="2.5" />
      <path d="M16 8.5v9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
      <circle cx="16" cy="22.5" r="1.75" fill="currentColor" />
    </svg>
  );
}

function Cross() {
  return (
    <svg viewBox="0 0 32 32" className="h-9 w-9" aria-hidden="true">
      <circle cx="16" cy="16" r="14" fill="none" stroke="currentColor" strokeWidth="2.5" />
      <path
        d="M11 11l10 10M21 11L11 21"
        stroke="currentColor"
        strokeWidth="3"
        strokeLinecap="round"
      />
    </svg>
  );
}
