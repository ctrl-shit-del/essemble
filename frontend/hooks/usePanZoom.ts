"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Pan and zoom for the seat map, clamped to the content.
 *
 * Applied as a transform on an inner <g> rather than by rewriting the SVG
 * viewBox: the viewBox stays the coordinate system the layout was computed
 * in, so seat positions, hit testing and the focus ring all keep working in
 * one space regardless of what the user has zoomed to.
 *
 * Clamping is the part that matters. Unclamped panning lets someone drag the
 * hall off screen and leaves them staring at empty space with no way back,
 * which on a touch device is easy to do by accident.
 */

export type Viewport = { scale: number; x: number; y: number };

const MIN_SCALE = 1;
const MAX_SCALE = 4;
const ZOOM_STEP = 1.35;

export type PanZoom = {
  viewport: Viewport;
  bind: {
    onWheel: (event: React.WheelEvent) => void;
    onPointerDown: (event: React.PointerEvent) => void;
    onPointerMove: (event: React.PointerEvent) => void;
    onPointerUp: (event: React.PointerEvent) => void;
    onPointerCancel: (event: React.PointerEvent) => void;
  };
  zoomIn: () => void;
  zoomOut: () => void;
  reset: () => void;
  canZoomIn: boolean;
  canZoomOut: boolean;
  isPanning: boolean;
};

/**
 * @param width  content width in SVG user units
 * @param height content height in SVG user units
 */
export function usePanZoom(width: number, height: number): PanZoom {
  const [viewport, setViewport] = useState<Viewport>({ scale: 1, x: 0, y: 0 });
  const [isPanning, setIsPanning] = useState(false);

  const dragStart = useRef<{ x: number; y: number; vx: number; vy: number } | null>(
    null,
  );
  // Live pinch pointers, keyed by pointerId.
  const pointers = useRef(new Map<number, { x: number; y: number }>());
  const pinchStart = useRef<{ distance: number; scale: number } | null>(null);

  /**
   * Keep the content overlapping the viewport.
   *
   * At scale 1 the only valid offset is 0 -- the content exactly fills the
   * frame, so any pan would introduce a gap.
   */
  const clamp = useCallback(
    (next: Viewport): Viewport => {
      const scale = Math.min(MAX_SCALE, Math.max(MIN_SCALE, next.scale));
      const overflowX = width * (scale - 1);
      const overflowY = height * (scale - 1);
      return {
        scale,
        x: Math.min(0, Math.max(-overflowX, next.x)),
        y: Math.min(0, Math.max(-overflowY, next.y)),
      };
    },
    [width, height],
  );

  /** Zoom about a fixed point, so the seat under the cursor stays put. */
  const zoomAbout = useCallback(
    (factor: number, originX: number, originY: number) => {
      setViewport((current) => {
        const scale = Math.min(
          MAX_SCALE,
          Math.max(MIN_SCALE, current.scale * factor),
        );
        const applied = scale / current.scale;
        return clamp({
          scale,
          x: originX - (originX - current.x) * applied,
          y: originY - (originY - current.y) * applied,
        });
      });
    },
    [clamp],
  );

  const toLocal = (event: { currentTarget: Element; clientX: number; clientY: number }) => {
    const rect = event.currentTarget.getBoundingClientRect();
    // Normalised to the content's own units, so zoom origin is correct
    // whatever size the SVG is rendered at.
    return {
      x: ((event.clientX - rect.left) / rect.width) * width,
      y: ((event.clientY - rect.top) / rect.height) * height,
    };
  };

  const onWheel = useCallback(
    (event: React.WheelEvent) => {
      // ONLY a pinch/ctrl gesture zooms. A plain wheel must scroll the page.
      //
      // Browsers report a trackpad pinch as a wheel event with ctrlKey set,
      // which is the same signal the browser's own page zoom uses -- so this
      // covers pinch on a trackpad and ctrl+wheel on a mouse, and nothing
      // else. Treating a large deltaY as "deliberate" instead would hijack
      // every ordinary scroll over the map, because a mouse wheel sends
      // deltas well above any sensible threshold.
      if (!event.ctrlKey && !event.metaKey) return;
      event.preventDefault();
      const local = toLocal(event);
      zoomAbout(event.deltaY < 0 ? ZOOM_STEP : 1 / ZOOM_STEP, local.x, local.y);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [zoomAbout, width, height],
  );

  const onPointerDown = useCallback(
    (event: React.PointerEvent) => {
      // Never capture a click that is landing on a seat.
      if ((event.target as Element).closest("[data-seat]")) return;

      pointers.current.set(event.pointerId, {
        x: event.clientX,
        y: event.clientY,
      });

      if (pointers.current.size === 2) {
        const [a, b] = [...pointers.current.values()];
        pinchStart.current = {
          distance: Math.hypot(a.x - b.x, a.y - b.y),
          scale: viewport.scale,
        };
        dragStart.current = null;
        return;
      }

      (event.currentTarget as Element).setPointerCapture?.(event.pointerId);
      dragStart.current = {
        x: event.clientX,
        y: event.clientY,
        vx: viewport.x,
        vy: viewport.y,
      };
      setIsPanning(true);
    },
    [viewport],
  );

  const onPointerMove = useCallback(
    (event: React.PointerEvent) => {
      if (!pointers.current.has(event.pointerId)) return;
      pointers.current.set(event.pointerId, {
        x: event.clientX,
        y: event.clientY,
      });

      if (pointers.current.size === 2 && pinchStart.current) {
        const [a, b] = [...pointers.current.values()];
        const distance = Math.hypot(a.x - b.x, a.y - b.y);
        const factor = distance / pinchStart.current.distance;
        const target = pinchStart.current.scale * factor;
        setViewport((current) =>
          clamp({ ...current, scale: target }),
        );
        return;
      }

      const start = dragStart.current;
      if (!start) return;
      const rect = event.currentTarget.getBoundingClientRect();
      const dx = ((event.clientX - start.x) / rect.width) * width;
      const dy = ((event.clientY - start.y) / rect.height) * height;
      setViewport((current) =>
        clamp({ ...current, x: start.vx + dx, y: start.vy + dy }),
      );
    },
    [clamp, width, height],
  );

  const endPointer = useCallback((event: React.PointerEvent) => {
    pointers.current.delete(event.pointerId);
    if (pointers.current.size < 2) pinchStart.current = null;
    if (pointers.current.size === 0) {
      dragStart.current = null;
      setIsPanning(false);
    }
  }, []);

  // Re-clamp when the content resizes under a zoomed viewport, or the map
  // can be left scrolled past its own edge.
  useEffect(() => {
    setViewport((current) => clamp(current));
  }, [clamp]);

  return {
    viewport,
    bind: {
      onWheel,
      onPointerDown,
      onPointerMove,
      onPointerUp: endPointer,
      onPointerCancel: endPointer,
    },
    zoomIn: () => zoomAbout(ZOOM_STEP, width / 2, height / 2),
    zoomOut: () => zoomAbout(1 / ZOOM_STEP, width / 2, height / 2),
    reset: () => setViewport({ scale: 1, x: 0, y: 0 }),
    canZoomIn: viewport.scale < MAX_SCALE - 0.001,
    canZoomOut: viewport.scale > MIN_SCALE + 0.001,
    isPanning,
  };
}
