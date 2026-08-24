"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { API_BASE_URL, isApiError } from "@/lib/api";
import {
  diffSeatStatuses,
  fetchSeatMap,
  patchSeatStatuses,
} from "@/lib/seatmap";
import { seatChangeEventSchema, type SeatMap } from "@/lib/types";

/**
 * Live seat map: two transports, one state.
 *
 * BOTH paths run, always. SSE is the upgrade, the versioned poll is the
 * mechanism -- the backend says as much, because LISTEN/NOTIFY cannot survive
 * a serverless deployment or a transaction pooler, and a stream that connects
 * and then silently delivers nothing is worse than no stream at all. So when
 * SSE is live the poll backs off to 30s as a safety net rather than stopping:
 * if the stream dies quietly, the map is at most 30 seconds stale instead of
 * permanently wrong.
 *
 * RECONCILIATION
 * Both transports carry seat_version, which is what makes them safe to mix.
 * An event is applied only when its version is >= the version we already
 * hold, so a stream frame that arrives after a poll has already jumped past
 * it cannot resurrect stale seats. `>=` rather than `>` is deliberate: one
 * version bump can emit several events -- a cancellation announces some seats
 * held for an offer and the rest available under a single version -- and `>`
 * would drop all but the first.
 */

const POLL_INTERVAL_FALLBACK_MS = 5_000;
const POLL_INTERVAL_WITH_SSE_MS = 30_000;
const SSE_BACKOFF_START_MS = 1_000;
const SSE_BACKOFF_MAX_MS = 30_000;
/** How long a changed seat stays flagged for the transition animation. */
const FLASH_MS = 900;

export type Transport = "connecting" | "live" | "polling";

export type FlashKind = "change" | "lost";

export type LiveSeatMap = {
  map: SeatMap | null;
  loading: boolean;
  error: Error | null;
  transport: Transport;
  /** seat_id -> flash, consumed by the renderer to animate a change. */
  flashes: Map<number, { kind: FlashKind; nonce: number }>;
  refresh: () => Promise<void>;
  /** Flag seats red, e.g. the losers of a SEAT_UNAVAILABLE race. */
  flashSeats: (seatIds: number[], kind: FlashKind) => void;
};

export function useLiveSeatMap(showId: number | null): LiveSeatMap {
  const [map, setMap] = useState<SeatMap | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [transport, setTransport] = useState<Transport>("connecting");
  const [flashes, setFlashes] = useState<Map<number, { kind: FlashKind; nonce: number }>>(
    new Map(),
  );

  // The version we believe we are at. A ref, not state: the poll and the
  // stream both read it from callbacks that must not be re-created on every
  // version bump, or each bump would tear down and rebuild both transports.
  const versionRef = useRef<number>(-1);
  const flashTimers = useRef(new Map<number, ReturnType<typeof setTimeout>>());
  const nonceRef = useRef(0);

  /* ------------------------------------------------------------- flashing */

  const flashSeats = useCallback((seatIds: number[], kind: FlashKind) => {
    if (seatIds.length === 0) return;
    nonceRef.current += 1;
    const nonce = nonceRef.current;

    setFlashes((current) => {
      const next = new Map(current);
      for (const id of seatIds) next.set(id, { kind, nonce });
      return next;
    });

    for (const id of seatIds) {
      const existing = flashTimers.current.get(id);
      if (existing) clearTimeout(existing);
      flashTimers.current.set(
        id,
        setTimeout(() => {
          flashTimers.current.delete(id);
          setFlashes((current) => {
            // Only clear if this flash is still the current one; a newer
            // change to the same seat owns the flag now.
            if (current.get(id)?.nonce !== nonce) return current;
            const next = new Map(current);
            next.delete(id);
            return next;
          });
        }, FLASH_MS),
      );
    }
  }, []);

  /* ---------------------------------------------------------------- fetch */

  const load = useCallback(
    async (signal?: AbortSignal) => {
      if (showId === null) return;
      const since = versionRef.current >= 0 ? versionRef.current : undefined;
      const fresh = await fetchSeatMap(showId, since, signal);

      // 304: nothing has moved. This is the common case and does nothing.
      if (fresh === null) return;

      setMap((previous) => {
        // Only animate when we had something to compare against; the first
        // load must not flash all 216 seats.
        if (previous) {
          const changed = diffSeatStatuses(previous.seats, fresh.seats);
          if (changed.length > 0) flashSeats(changed, "change");
        }
        return fresh;
      });
      versionRef.current = fresh.seat_version;
      setError(null);
    },
    [showId, flashSeats],
  );

  const refresh = useCallback(async () => {
    try {
      // Force a full body: after a mutation we want the authoritative map,
      // not a 304 against a version the server may have already passed.
      versionRef.current = -1;
      await load();
    } catch (caught) {
      if (isApiError(caught) && caught.code === "TIMEOUT") return;
      setError(caught as Error);
    }
  }, [load]);

  /* ----------------------------------------------------------- first load */

  useEffect(() => {
    if (showId === null) return;
    const controller = new AbortController();
    let cancelled = false;

    setLoading(true);
    setMap(null);
    versionRef.current = -1;

    load(controller.signal)
      .catch((caught) => {
        if (cancelled) return;
        if (isApiError(caught) && caught.code === "TIMEOUT") return;
        setError(caught as Error);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [showId, load]);

  /* ------------------------------------------------------------------ SSE */

  useEffect(() => {
    if (showId === null) return;
    if (typeof window === "undefined" || typeof EventSource === "undefined") {
      setTransport("polling");
      return;
    }

    let source: EventSource | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let backoff = SSE_BACKOFF_START_MS;
    let closed = false;

    const connect = () => {
      if (closed) return;
      // The stream endpoint is deliberately unauthenticated -- seat status is
      // public -- which is what makes EventSource usable at all, since it
      // cannot send an Authorization header.
      source = new EventSource(`${API_BASE_URL}/api/shows/${showId}/seatmap/stream`);

      source.onopen = () => {
        backoff = SSE_BACKOFF_START_MS;
        setTransport("live");
      };

      source.onmessage = (event) => {
        const parsed = seatChangeEventSchema.safeParse(
          safeJsonParse(event.data),
        );
        // A frame we cannot read is not a reason to tear down the stream;
        // the poll will reconcile whatever it described.
        if (!parsed.success) return;
        const change = parsed.data;
        if (change.show_id !== showId) return;
        // Stale frame: a poll has already carried us past it.
        if (change.seat_version < versionRef.current) return;

        setMap((current) => {
          if (!current) return current;
          const { seats, changed } = patchSeatStatuses(
            current.seats,
            change.seat_ids,
            change.status,
          );
          if (changed.length > 0) flashSeats(changed, "change");
          return { ...current, seats, seat_version: change.seat_version };
        });
        versionRef.current = Math.max(versionRef.current, change.seat_version);
      };

      source.onerror = () => {
        // EventSource retries on its own, but with no backoff cap and no way
        // to tell the UI. Take it over explicitly so the indicator is honest.
        source?.close();
        source = null;
        if (closed) return;
        setTransport("polling");
        reconnectTimer = setTimeout(connect, backoff);
        backoff = Math.min(backoff * 2, SSE_BACKOFF_MAX_MS);
      };
    };

    setTransport("connecting");
    connect();

    return () => {
      closed = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      source?.close();
    };
  }, [showId, flashSeats]);

  /* ----------------------------------------------------------------- poll */

  useEffect(() => {
    if (showId === null) return;

    // Never disabled, only slowed. A silently dead stream would otherwise
    // leave the map permanently wrong with a confident "live" badge.
    const interval =
      transport === "live" ? POLL_INTERVAL_WITH_SSE_MS : POLL_INTERVAL_FALLBACK_MS;

    const timer = setInterval(() => {
      // Polling a hidden tab wastes the free tier's request budget and the
      // visibilitychange handler below catches up the moment it returns.
      if (document.visibilityState !== "visible") return;
      void load().catch(() => {
        // A failed poll is not worth surfacing: the next tick retries, and
        // the transport badge already shows we are not on the stream.
      });
    }, interval);

    const onVisible = () => {
      if (document.visibilityState === "visible") void load().catch(() => {});
    };
    document.addEventListener("visibilitychange", onVisible);

    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [showId, transport, load]);

  /* -------------------------------------------------------------- cleanup */

  useEffect(() => {
    const timers = flashTimers.current;
    return () => {
      for (const timer of timers.values()) clearTimeout(timer);
      timers.clear();
    };
  }, []);

  return useMemo(
    () => ({ map, loading, error, transport, flashes, refresh, flashSeats }),
    [map, loading, error, transport, flashes, refresh, flashSeats],
  );
}

function safeJsonParse(raw: string): unknown {
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}
