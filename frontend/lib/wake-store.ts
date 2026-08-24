/**
 * "The server is waking up" state.
 *
 * The API is hosted on a free tier that suspends the instance after ~15
 * minutes of inactivity. The next request then pays a cold start of up to a
 * minute. Without this, the first visit of the day looks like a broken app:
 * spinners that never resolve, then a timeout.
 *
 * The rule is narrow on purpose. Only the FIRST request of a session arms
 * the timer, and only if it is still in flight after WAKE_THRESHOLD_MS. Once
 * anything has come back, the instance is warm and a later slow request is
 * just a slow request -- calling that "waking up" would be a lie that trains
 * people to ignore the banner.
 */

const WAKE_THRESHOLD_MS = 3000;

export type WakeState = "idle" | "waking" | "awake";

let state: WakeState = "idle";
/** Flips the moment any response lands, so the timer arms at most once. */
let hasCompletedARequest = false;
let inFlight = 0;
let timer: ReturnType<typeof setTimeout> | null = null;

type Listener = (next: WakeState) => void;
const listeners = new Set<Listener>();

function set(next: WakeState) {
  if (state === next) return;
  state = next;
  for (const listener of listeners) listener(state);
}

export function subscribeWake(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function getWakeState(): WakeState {
  return state;
}

function clearTimer() {
  if (timer !== null) {
    clearTimeout(timer);
    timer = null;
  }
}

/** Called by lib/api.ts as a request leaves. */
export function noteRequestStart() {
  inFlight += 1;
  if (hasCompletedARequest || timer !== null) return;
  timer = setTimeout(() => {
    // Still nothing back after the threshold: this is a cold start.
    if (!hasCompletedARequest && inFlight > 0) set("waking");
  }, WAKE_THRESHOLD_MS);
}

/** Called by lib/api.ts when a request settles, successfully or not. */
export function noteRequestEnd(reachedServer: boolean) {
  inFlight = Math.max(0, inFlight - 1);
  if (!reachedServer) {
    // A network failure says nothing about whether the instance is awake.
    // Leave the banner up; a retry will resolve it either way.
    if (inFlight === 0) clearTimer();
    return;
  }
  hasCompletedARequest = true;
  clearTimer();
  // Only announce "awake" to clear a banner we actually showed.
  set(state === "waking" ? "awake" : "idle");
}

/** Test seam, and used when a hard logout resets the session. */
export function resetWakeState() {
  clearTimer();
  state = "idle";
  hasCompletedARequest = false;
  inFlight = 0;
}

export { WAKE_THRESHOLD_MS };
