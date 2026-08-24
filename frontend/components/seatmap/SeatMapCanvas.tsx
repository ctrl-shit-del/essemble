"use client";

import { useCallback, useEffect, useMemo, useRef } from "react";
import { SeatPatternDefs, seatVisual } from "@/components/ui/SeatPattern";
import { usePanZoom } from "@/hooks/usePanZoom";
import type { FlashKind } from "@/hooks/useLiveSeatMap";
import {
  categoryName,
  computeCategoryBands,
  computeGeometry,
  formatMoney,
  groupIntoRows,
  priceOf,
  seatLabel,
} from "@/lib/seatmap";
import type { SeatMap, SeatMapSeat } from "@/lib/types";
import { cn } from "@/lib/cn";

/**
 * The seat map, in SVG.
 *
 * SVG rather than a div per seat: pan, zoom and hit testing come free in one
 * coordinate system, and a 500-seat hall stays one paint instead of 500
 * layout boxes.
 *
 * EVERY position comes from the stored x/y. Nothing is derived from array
 * index or seat_number -- see lib/seatmap.ts for why that distinction is not
 * stylistic.
 */

/** SVG user units per column/row step. */
const CELL = 30;
const SEAT = 22;
const ROW_LABEL_GUTTER = 34;
const CATEGORY_GUTTER = 8;
const TOP_PAD = 74; // room for the screen arc
const BOTTOM_PAD = 16;

export type SeatMapCanvasProps = {
  map: SeatMap;
  selected: Set<number>;
  flashes: Map<number, { kind: FlashKind; nonce: number }>;
  onToggle: (seat: SeatMapSeat) => void;
  onBlocked: (seat: SeatMapSeat) => void;
  focusedSeatId: number | null;
  onFocusSeat: (seatId: number | null) => void;
};

export function SeatMapCanvas({
  map,
  selected,
  flashes,
  onToggle,
  onBlocked,
  focusedSeatId,
  onFocusSeat,
}: SeatMapCanvasProps) {
  const geometry = useMemo(() => computeGeometry(map.seats), [map.seats]);
  const rows = useMemo(() => groupIntoRows(map.seats), [map.seats]);
  const bands = useMemo(() => computeCategoryBands(map.seats), [map.seats]);

  const contentWidth =
    ROW_LABEL_GUTTER + geometry.columns * CELL + CATEGORY_GUTTER + 96;
  const contentHeight = TOP_PAD + geometry.rows * CELL + BOTTOM_PAD;

  const panZoom = usePanZoom(contentWidth, contentHeight);
  const seatRefs = useRef(new Map<number, SVGGElement | null>());

  // Position helpers. Both subtract the minimum, so a hall whose coordinates
  // do not start at zero still renders flush.
  const seatX = useCallback(
    (seat: SeatMapSeat) =>
      ROW_LABEL_GUTTER + (seat.x - geometry.minX) * CELL + CELL / 2,
    [geometry.minX],
  );
  const seatY = useCallback(
    (seat: SeatMapSeat) => TOP_PAD + (seat.y - geometry.minY) * CELL + CELL / 2,
    [geometry.minY],
  );

  /* ------------------------------------------------------------- keyboard */

  // Row-major order, so arrow keys move by geometry rather than by the order
  // the API happened to return seats in.
  const navigate = useCallback(
    (from: number, direction: "up" | "down" | "left" | "right") => {
      const current = map.seats.find((seat) => seat.seat_id === from);
      if (!current) return;

      if (direction === "left" || direction === "right") {
        const row = rows.find((item) => item.y === current.y);
        if (!row) return;
        const index = row.seats.findIndex((seat) => seat.seat_id === from);
        const next = row.seats[index + (direction === "right" ? 1 : -1)];
        if (next) onFocusSeat(next.seat_id);
        return;
      }

      const rowIndex = rows.findIndex((item) => item.y === current.y);
      const nextRow = rows[rowIndex + (direction === "down" ? 1 : -1)];
      if (!nextRow) return;
      // Nearest by x, not by index: rows differ in length and in where their
      // aisles fall, so index would drift sideways as you move down the hall.
      let best = nextRow.seats[0];
      let bestDistance = Infinity;
      for (const seat of nextRow.seats) {
        const distance = Math.abs(seat.x - current.x);
        if (distance < bestDistance) {
          bestDistance = distance;
          best = seat;
        }
      }
      if (best) onFocusSeat(best.seat_id);
    },
    [map.seats, rows, onFocusSeat],
  );

  // Move real DOM focus, so a screen reader follows and the browser scrolls
  // the seat into view on its own.
  useEffect(() => {
    if (focusedSeatId === null) return;
    seatRefs.current.get(focusedSeatId)?.focus({ preventScroll: false });
  }, [focusedSeatId]);

  const onKeyDown = (event: React.KeyboardEvent, seat: SeatMapSeat) => {
    const keys: Record<string, "up" | "down" | "left" | "right"> = {
      ArrowUp: "up",
      ArrowDown: "down",
      ArrowLeft: "left",
      ArrowRight: "right",
    };
    const direction = keys[event.key];
    if (direction) {
      event.preventDefault();
      navigate(seat.seat_id, direction);
      return;
    }
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      if (seat.status === "available") onToggle(seat);
      else onBlocked(seat);
    }
  };

  /* ---------------------------------------------------------------- render */

  const firstSeatId = rows[0]?.seats[0]?.seat_id ?? null;

  return (
    <div className="relative">
      <ZoomControls panZoom={panZoom} />

      <svg
        viewBox={`0 0 ${contentWidth} ${contentHeight}`}
        className={cn(
          "w-full touch-none select-none",
          panZoom.isPanning ? "cursor-grabbing" : "cursor-grab",
        )}
        role="group"
        aria-label={`Seat map for ${map.event_title} at ${map.venue_name}, ${map.screen_name}`}
        {...panZoom.bind}
      >
        <SeatPatternDefs />

        <g
          transform={`translate(${panZoom.viewport.x} ${panZoom.viewport.y}) scale(${panZoom.viewport.scale})`}
        >
          <ScreenArc width={contentWidth} />

          {/* Category bands, derived from the seats that are actually here. */}
          {bands.map((band) => {
            const top = TOP_PAD + (band.minY - geometry.minY) * CELL;
            const height = (band.maxY - band.minY + 1) * CELL;
            const x = ROW_LABEL_GUTTER + geometry.columns * CELL + CATEGORY_GUTTER;
            return (
              <g key={band.categoryId}>
                <line
                  x1={x + 6}
                  y1={top + 4}
                  x2={x + 6}
                  y2={top + height - 4}
                  stroke="var(--color-border-strong)"
                  strokeWidth="1"
                />
                <text
                  x={x + 14}
                  y={top + height / 2 - 4}
                  className="fill-[var(--color-text)] text-[11px]"
                  dominantBaseline="middle"
                >
                  {categoryName(map, band.categoryId)}
                </text>
                <text
                  x={x + 14}
                  y={top + height / 2 + 10}
                  className="fill-[var(--color-muted)] text-[10px]"
                  dominantBaseline="middle"
                >
                  {formatMoney(priceOf(map, band.categoryId))}
                </text>
              </g>
            );
          })}

          {/* Row labels, keyed off each row's own y. A hall missing a row
              leaves a gap here rather than renumbering everything below. */}
          {rows.map((row) => (
            <text
              key={`label-${row.y}`}
              x={ROW_LABEL_GUTTER - 14}
              y={TOP_PAD + (row.y - geometry.minY) * CELL + CELL / 2}
              textAnchor="middle"
              dominantBaseline="middle"
              className="fill-[var(--color-muted)] text-[11px]"
            >
              {row.label}
            </text>
          ))}

          {map.seats.map((seat) => (
            <Seat
              key={seat.seat_id}
              seat={seat}
              cx={seatX(seat)}
              cy={seatY(seat)}
              selected={selected.has(seat.seat_id)}
              flash={flashes.get(seat.seat_id)}
              focusable={
                focusedSeatId === null
                  ? seat.seat_id === firstSeatId
                  : seat.seat_id === focusedSeatId
              }
              registerRef={(element) => {
                if (element) seatRefs.current.set(seat.seat_id, element);
                else seatRefs.current.delete(seat.seat_id);
              }}
              onActivate={() =>
                seat.status === "available" ? onToggle(seat) : onBlocked(seat)
              }
              onFocus={() => onFocusSeat(seat.seat_id)}
              onKeyDown={(event) => onKeyDown(event, seat)}
            />
          ))}
        </g>
      </svg>
    </div>
  );
}

/* ------------------------------------------------------------------- seat */

type SeatProps = {
  seat: SeatMapSeat;
  cx: number;
  cy: number;
  selected: boolean;
  flash?: { kind: FlashKind; nonce: number };
  focusable: boolean;
  registerRef: (element: SVGGElement | null) => void;
  onActivate: () => void;
  onFocus: () => void;
  onKeyDown: (event: React.KeyboardEvent) => void;
};

function Seat({
  seat,
  cx,
  cy,
  selected,
  flash,
  focusable,
  registerRef,
  onActivate,
  onFocus,
  onKeyDown,
}: SeatProps) {
  // `selected` is client-only and outranks `available` for display. It is
  // never sent to the server on click and never written to the map -- only a
  // successful POST /api/holds turns a selection into real state.
  const state = selected ? "selected" : seat.status;
  const visual = seatVisual(state);
  const interactive = seat.status === "available";

  const label = seatLabel(seat);
  const description =
    seat.status === "booked"
      ? `${label}, booked`
      : seat.status === "held"
        ? `${label}, held by someone else`
        : selected
          ? `${label}, selected`
          : `${label}, available`;

  return (
    <g
      ref={registerRef}
      data-seat={seat.seat_id}
      tabIndex={focusable ? 0 : -1}
      role="checkbox"
      aria-checked={selected}
      aria-disabled={!interactive}
      aria-label={description}
      onClick={onActivate}
      onFocus={onFocus}
      onKeyDown={onKeyDown}
      className={cn(
        "outline-none",
        interactive ? "cursor-pointer" : "cursor-not-allowed",
        "[&:focus-visible>.seat-focus]:opacity-100",
      )}
    >
      {/* Generous invisible hit area: a 22px seat is below the comfortable
          touch target, and enlarging the visible seat instead would close up
          the aisle gaps the geometry exists to preserve. */}
      <rect
        x={cx - CELL / 2}
        y={cy - CELL / 2}
        width={CELL}
        height={CELL}
        fill="transparent"
      />

      <rect
        x={cx - SEAT / 2}
        y={cy - SEAT / 2}
        width={SEAT}
        height={SEAT}
        rx={5}
        fill={visual.fill}
        stroke={visual.stroke}
        strokeWidth={visual.strokeWidth}
        className={cn(
          "transition-[fill,stroke] duration-200",
          interactive && !selected && "hover:stroke-[var(--color-text)]",
        )}
      />

      {/* The transition flash. A seat flipping to grey with no motion is
          invisible to someone watching two windows side by side, and that
          demonstration is the whole visible proof of the real-time layer.
          Keyed on the nonce so a repeat change to the same seat restarts the
          animation instead of being ignored as an unchanged element. */}
      {flash && (
        <rect
          key={flash.nonce}
          x={cx - SEAT / 2}
          y={cy - SEAT / 2}
          width={SEAT}
          height={SEAT}
          rx={5}
          fill="none"
          stroke={
            flash.kind === "lost" ? "var(--color-danger)" : "var(--color-accent)"
          }
          strokeWidth="2"
          className={
            flash.kind === "lost"
              ? "animate-[essemble-seat-lost_900ms_ease-out]"
              : "animate-[essemble-seat-change_900ms_ease-out]"
          }
          style={{ transformOrigin: `${cx}px ${cy}px` }}
          pointerEvents="none"
        />
      )}

      <rect
        className="seat-focus opacity-0 transition-opacity"
        x={cx - SEAT / 2 - 3}
        y={cy - SEAT / 2 - 3}
        width={SEAT + 6}
        height={SEAT + 6}
        rx={7}
        fill="none"
        stroke="var(--color-accent)"
        strokeWidth="2"
        pointerEvents="none"
      />
    </g>
  );
}

/* ----------------------------------------------------------------- screen */

function ScreenArc({ width }: { width: number }) {
  const inset = ROW_LABEL_GUTTER;
  const right = width - 96;
  return (
    <g aria-hidden="true">
      <path
        d={`M ${inset} 46 Q ${(inset + right) / 2} 16 ${right} 46`}
        fill="none"
        stroke="var(--color-accent)"
        strokeOpacity="0.5"
        strokeWidth="2"
        strokeLinecap="round"
      />
      <path
        d={`M ${inset} 46 Q ${(inset + right) / 2} 16 ${right} 46`}
        fill="none"
        stroke="var(--color-accent)"
        strokeOpacity="0.14"
        strokeWidth="12"
        strokeLinecap="round"
      />
      <text
        x={(inset + right) / 2}
        y={62}
        textAnchor="middle"
        className="fill-[var(--color-muted)] text-[10px] tracking-[0.28em]"
      >
        ALL EYES THIS WAY
      </text>
    </g>
  );
}

/* ----------------------------------------------------------------- zoom UI */

function ZoomControls({ panZoom }: { panZoom: ReturnType<typeof usePanZoom> }) {
  return (
    <div className="absolute right-3 top-3 z-10 flex flex-col overflow-hidden rounded-lg border border-border bg-surface">
      <ZoomButton onClick={panZoom.zoomIn} disabled={!panZoom.canZoomIn} label="Zoom in">
        <svg viewBox="0 0 14 14" className="h-3.5 w-3.5" aria-hidden="true">
          <path d="M7 2v10M2 7h10" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
        </svg>
      </ZoomButton>
      <ZoomButton onClick={panZoom.zoomOut} disabled={!panZoom.canZoomOut} label="Zoom out">
        <svg viewBox="0 0 14 14" className="h-3.5 w-3.5" aria-hidden="true">
          <path d="M2 7h10" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
        </svg>
      </ZoomButton>
      <ZoomButton onClick={panZoom.reset} disabled={!panZoom.canZoomOut} label="Reset zoom">
        <svg viewBox="0 0 14 14" className="h-3.5 w-3.5" aria-hidden="true">
          <rect
            x="2.5"
            y="2.5"
            width="9"
            height="9"
            rx="2"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
          />
        </svg>
      </ZoomButton>
    </div>
  );
}

function ZoomButton({
  onClick,
  disabled,
  label,
  children,
}: {
  onClick: () => void;
  disabled: boolean;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      title={label}
      className="grid h-8 w-8 place-items-center border-b border-border text-muted transition-colors last:border-b-0 hover:bg-surface-2 hover:text-text disabled:opacity-30 disabled:hover:bg-transparent"
    >
      {children}
    </button>
  );
}
