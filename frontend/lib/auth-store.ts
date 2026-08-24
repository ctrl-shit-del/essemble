/**
 * Where the access token lives.
 *
 * In memory is the source of truth; localStorage is a mirror so a refresh
 * does not log you out. Deliberately a plain module store rather than React
 * state: lib/api.ts needs the token from outside the component tree, and
 * threading it through every call site would mean every data hook takes a
 * token argument it does not otherwise care about.
 *
 * The token is a bearer credential in localStorage, which is readable by any
 * script on the origin. That is a real trade-off and the honest alternative
 * (an httpOnly cookie) needs the API to set cookies cross-origin, which this
 * backend does not do -- it is a bearer-token API. Given that, localStorage
 * is the option that survives a refresh.
 */

import type { User } from "./types";

const TOKEN_KEY = "essemble.token";
const USER_KEY = "essemble.user";

export type AuthSnapshot = {
  token: string | null;
  user: User | null;
};

let snapshot: AuthSnapshot = { token: null, user: null };

type Listener = (next: AuthSnapshot) => void;
const listeners = new Set<Listener>();

function emit() {
  for (const listener of listeners) listener(snapshot);
}

export function subscribe(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function getSnapshot(): AuthSnapshot {
  return snapshot;
}

/** Read by lib/api.ts on every request. */
export function getToken(): string | null {
  return snapshot.token;
}

export function setSession(token: string, user: User) {
  snapshot = { token, user };
  try {
    window.localStorage.setItem(TOKEN_KEY, token);
    window.localStorage.setItem(USER_KEY, JSON.stringify(user));
  } catch {
    // Private mode, or storage disabled. The session still works for this
    // tab; it just will not survive a reload.
  }
  emit();
}

export function clearSession() {
  snapshot = { token: null, user: null };
  try {
    window.localStorage.removeItem(TOKEN_KEY);
    window.localStorage.removeItem(USER_KEY);
  } catch {
    // Nothing to clean up if we could never write.
  }
  emit();
}

/**
 * Rehydrate from localStorage. Called once on mount, never during render --
 * reading storage while rendering would make the server and client markup
 * disagree and produce a hydration mismatch.
 */
export function restoreSession(): AuthSnapshot {
  try {
    const token = window.localStorage.getItem(TOKEN_KEY);
    const rawUser = window.localStorage.getItem(USER_KEY);
    if (token && rawUser) {
      snapshot = { token, user: JSON.parse(rawUser) as User };
      emit();
    }
  } catch {
    // A corrupt entry is not worth crashing the app over; start logged out.
    clearSession();
  }
  return snapshot;
}

/**
 * Keep tabs in step. Logging out in one tab must not leave another tab
 * holding a token it will only discover is dead on the next 401.
 */
export function listenForCrossTabChanges(): () => void {
  const onStorage = (event: StorageEvent) => {
    if (event.key !== TOKEN_KEY && event.key !== USER_KEY) return;
    const token = window.localStorage.getItem(TOKEN_KEY);
    const rawUser = window.localStorage.getItem(USER_KEY);
    snapshot =
      token && rawUser
        ? { token, user: JSON.parse(rawUser) as User }
        : { token: null, user: null };
    emit();
  };
  window.addEventListener("storage", onStorage);
  return () => window.removeEventListener("storage", onStorage);
}
