import { SeatLegend } from "@/components/ui/SeatPattern";

/**
 * Placeholder for the customer home.
 *
 * Pass 1 builds the foundation only -- no homepage, no seat map, no booking
 * flow. This page exists so the shell has something to frame, and shows the
 * seat vocabulary so the four states can be checked against a projector
 * before anything depends on them.
 */
export default function CustomerHome() {
  return (
    <div>
      <p className="text-[11px] uppercase tracking-[0.18em] text-accent">
        Foundation
      </p>
      <h1 className="mt-3 max-w-2xl font-display text-4xl leading-[1.1] tracking-tight text-text text-balance-title sm:text-5xl">
        The shell is up. The booking engine comes next.
      </h1>
      <p className="mt-4 max-w-xl text-[15px] leading-relaxed text-muted">
        Pass 1 covers the design system, the typed API client, auth, and the
        three shells. Pages, the seat map and the booking flow follow.
      </p>

      <section className="mt-14 border-t border-border pt-8">
        <h2 className="font-display text-lg text-text">Seat vocabulary</h2>
        <p className="mt-1.5 max-w-lg text-sm leading-relaxed text-muted">
          Four states separated by hue and texture rather than brightness, so
          they survive a projector and greyscale. Held carries a hatch as a
          second channel — it must never read as a dimmer version of selected.
        </p>
        <SeatLegend className="mt-5" />
      </section>
    </div>
  );
}
