/**
 * Seat state vocabulary.
 *
 * The four states differ in HUE, not shade, because they mean opposite things
 * and get read at distance off a projector:
 *
 *   available  outlined, muted border, transparent fill  -- takeable
 *   selected   solid amber                                -- yours
 *   held       desaturated neutral + diagonal hatch       -- someone else's
 *   booked     flat near-background, no border            -- gone
 *
 * `held` is deliberately NOT a dimmer amber. A darker amber sitting next to
 * selected amber is the one confusion that must not be possible: "mine" and
 * "not mine, and you cannot have it" would be separated only by brightness,
 * which is exactly what a projector, a bad angle, or colour-blindness
 * flattens. The hatch is a second, non-colour channel carrying the same
 * meaning, so the distinction survives even in greyscale.
 */

export const SEAT_HATCH_PATTERN_ID = "essemble-seat-hatch";

/**
 * Render ONCE per SVG that draws seats, inside the root <svg>. Referenced as
 * fill={`url(#${SEAT_HATCH_PATTERN_ID})`}.
 */
export function SeatPatternDefs() {
  return (
    <defs>
      <pattern
        id={SEAT_HATCH_PATTERN_ID}
        patternUnits="userSpaceOnUse"
        width="6"
        height="6"
        // 45 degrees: distinct from every horizontal and vertical edge in a
        // seat grid, so the texture never reads as part of the layout.
        patternTransform="rotate(45)"
      >
        <rect width="6" height="6" fill="var(--color-seat-held)" />
        <line
          x1="0"
          y1="0"
          x2="0"
          y2="6"
          stroke="var(--color-bg)"
          strokeWidth="2.5"
          strokeOpacity="0.55"
        />
      </pattern>
    </defs>
  );
}

export type SeatVisualState = "available" | "selected" | "held" | "booked";

/**
 * Presentation for one seat, as SVG attributes. Kept here rather than in the
 * seat map so the legend and the map cannot drift apart.
 */
export function seatVisual(state: SeatVisualState): {
  fill: string;
  stroke: string;
  strokeWidth: number;
} {
  switch (state) {
    case "selected":
      return { fill: "var(--color-accent)", stroke: "var(--color-accent)", strokeWidth: 1 };
    case "held":
      return {
        fill: `url(#${SEAT_HATCH_PATTERN_ID})`,
        stroke: "var(--color-seat-held)",
        strokeWidth: 1,
      };
    case "booked":
      return { fill: "var(--color-seat-booked)", stroke: "none", strokeWidth: 0 };
    case "available":
    default:
      return { fill: "transparent", stroke: "var(--color-muted)", strokeWidth: 1 };
  }
}

const LABELS: Record<SeatVisualState, string> = {
  available: "Available",
  selected: "Your selection",
  held: "Held by someone else",
  booked: "Booked",
};

/** A single swatch, drawn with the same code path the seat map will use. */
export function SeatSwatch({ state }: { state: SeatVisualState }) {
  const visual = seatVisual(state);
  return (
    <span className="inline-flex items-center gap-2">
      <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
        <SeatPatternDefs />
        <rect
          x="1.5"
          y="1.5"
          width="15"
          height="15"
          rx="4"
          fill={visual.fill}
          stroke={visual.stroke}
          strokeWidth={visual.strokeWidth}
        />
      </svg>
      <span className="text-[13px] text-muted">{LABELS[state]}</span>
    </span>
  );
}

export function SeatLegend({ className }: { className?: string }) {
  return (
    <div className={className}>
      <ul className="flex flex-wrap items-center gap-x-5 gap-y-2">
        {(["available", "selected", "held", "booked"] as SeatVisualState[]).map(
          (state) => (
            <li key={state}>
              <SeatSwatch state={state} />
            </li>
          ),
        )}
      </ul>
    </div>
  );
}
