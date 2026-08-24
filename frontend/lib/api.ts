/**
 * The only place this app talks to the API.
 *
 * Three things it exists to get right:
 *
 *  1. Errors arrive as { error: { code, message, details } } and callers
 *     branch on `code`, never on the HTTP status. The backend reuses statuses
 *     deliberately -- 409 is both SEAT_UNAVAILABLE and HOLD_LIMIT_EXCEEDED,
 *     410 is both HOLD_EXPIRED and OFFER_EXPIRED -- so status-based handling
 *     would show the wrong message to a real user in a real race.
 *
 *  2. Idempotency-Key on the two unsafe POSTs the backend replays. Without
 *     it, a retry after a timeout on a cold start can produce a second hold.
 *
 *  3. The cold-start banner, via lib/wake-store.
 */

import { z } from "zod";
import { getToken } from "./auth-store";
import { noteRequestEnd, noteRequestStart } from "./wake-store";
import {
  errorEnvelopeSchema,
  seatUnavailableDetailSchema,
  validationDetailSchema,
  type AnyErrorCode,
  type ErrorCode,
} from "./types";

export const API_BASE_URL = (
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000"
).replace(/\/+$/, "");

/**
 * Generous, because a cold start legitimately takes ~60s. A shorter timeout
 * would abort exactly the request the wake banner exists to explain.
 */
const DEFAULT_TIMEOUT_MS = 90_000;

/* ------------------------------------------------------------------ error */

export class ApiError extends Error {
  readonly code: AnyErrorCode;
  readonly status: number;
  readonly details: unknown;

  constructor(
    code: AnyErrorCode,
    message: string,
    status: number,
    details: unknown = null,
  ) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
    this.details = details;
  }

  /** True for the codes a booking flow is expected to handle, not report. */
  get isExpectedRace(): boolean {
    return (
      this.code === "SEAT_UNAVAILABLE" ||
      this.code === "HOLD_EXPIRED" ||
      this.code === "OFFER_EXPIRED"
    );
  }

  get isAuthFailure(): boolean {
    return this.code === "UNAUTHENTICATED";
  }

  /** Seats lost to someone else, when the code is SEAT_UNAVAILABLE. */
  get lostSeatIds(): number[] {
    const parsed = seatUnavailableDetailSchema.safeParse(this.details);
    return parsed.success ? parsed.data.seat_ids : [];
  }

  /** Field errors, when the code is VALIDATION_ERROR. */
  get fieldErrors(): { field: string; message: string }[] {
    const parsed = validationDetailSchema.safeParse(this.details);
    return parsed.success ? parsed.data : [];
  }

  /** Server-side correlation id, when the code is INTERNAL_ERROR. */
  get correlationId(): string | null {
    if (
      this.details &&
      typeof this.details === "object" &&
      "correlation_id" in this.details
    ) {
      const value = (this.details as { correlation_id: unknown }).correlation_id;
      return typeof value === "string" ? value : null;
    }
    return null;
  }
}

export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError;
}

/** Narrowing helper, so callers can `if (hasCode(e, "SEAT_UNAVAILABLE"))`. */
export function hasCode(error: unknown, ...codes: ErrorCode[]): boolean {
  return isApiError(error) && codes.includes(error.code as ErrorCode);
}

/* ------------------------------------------------------------ idempotency */

/**
 * The backend applies its replay ledger to exactly these two endpoints, keyed
 * on (Idempotency-Key, user). Sending a key elsewhere is harmless but
 * meaningless, and sending one to offer-claim would be actively wrong -- that
 * token is single-use by construction and a second attempt is meant to fail.
 */
function needsIdempotencyKey(method: string, path: string): boolean {
  if (method !== "POST") return false;
  return path === "/api/holds" || /^\/api\/holds\/[^/]+\/confirm$/.test(path);
}

function newIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `k-${Date.now()}-${Math.random().toString(36).slice(2, 12)}`;
}

/* -------------------------------------------------------------- transport */

export type RequestOptions = {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  body?: unknown;
  /** Reuse a key across retries of the same logical operation. */
  idempotencyKey?: string;
  signal?: AbortSignal;
  timeoutMs?: number;
  /** Skip the Authorization header (offer preview is deliberately public). */
  anonymous?: boolean;
  /**
   * Return null for 204/304 instead of trying to parse an absent body.
   *
   * The seat map uses this: `?since=<seat_version>` answers 304 when nothing
   * has moved, which is a normal, frequent, successful outcome of polling --
   * not an error and not an empty result.
   */
  allowEmpty?: boolean;
  query?: Record<string, string | number | boolean | undefined | null>;
};

function buildUrl(path: string, query?: RequestOptions["query"]): string {
  const url = new URL(`${API_BASE_URL}${path}`);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== null) {
        url.searchParams.set(key, String(value));
      }
    }
  }
  return url.toString();
}

/**
 * Perform a request and return the parsed body.
 *
 * `schema` is applied to successful responses. A shape mismatch throws
 * MALFORMED_RESPONSE rather than handing back a half-valid object, because
 * the alternative is a seat map that renders empty with no explanation.
 */
export async function request<T>(
  path: string,
  schema: z.ZodType<T>,
  options: RequestOptions = {},
): Promise<T> {
  const {
    method = "GET",
    body,
    idempotencyKey,
    signal,
    timeoutMs = DEFAULT_TIMEOUT_MS,
    anonymous = false,
    allowEmpty = false,
    query,
  } = options;

  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";

  if (!anonymous) {
    const token = getToken();
    if (token) headers.Authorization = `Bearer ${token}`;
  }

  if (needsIdempotencyKey(method, path)) {
    headers["Idempotency-Key"] = idempotencyKey ?? newIdempotencyKey();
  }

  const controller = new AbortController();
  const onAbort = () => controller.abort();
  signal?.addEventListener("abort", onAbort, { once: true });
  const timeout = setTimeout(() => controller.abort(), timeoutMs);

  noteRequestStart();
  let reachedServer = false;

  try {
    const response = await fetch(buildUrl(path, query), {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
      cache: "no-store",
    });
    reachedServer = true;

    // 204 and 304 carry no body by definition.
    if (response.status === 204 || response.status === 304) {
      if (allowEmpty) return null as T;
      return schema.parse(undefined as unknown as T);
    }

    const text = await response.text();
    let payload: unknown = null;
    if (text) {
      try {
        payload = JSON.parse(text);
      } catch {
        throw new ApiError(
          "MALFORMED_RESPONSE",
          "The server sent a response this app could not read.",
          response.status,
        );
      }
    }

    if (!response.ok) throw toApiError(payload, response.status);

    const parsed = schema.safeParse(payload);
    if (!parsed.success) {
      throw new ApiError(
        "MALFORMED_RESPONSE",
        "The server sent data in an unexpected shape.",
        response.status,
        parsed.error.flatten(),
      );
    }
    return parsed.data;
  } catch (error) {
    if (isApiError(error)) throw error;

    if (error instanceof DOMException && error.name === "AbortError") {
      // Distinguish "we gave up" from "the caller navigated away".
      if (signal?.aborted) throw new ApiError("TIMEOUT", "Request cancelled.", 0);
      throw new ApiError(
        "TIMEOUT",
        "The server took too long to respond. It may be starting up.",
        0,
      );
    }

    throw new ApiError(
      "NETWORK_ERROR",
      "Could not reach the server. Check your connection and try again.",
      0,
    );
  } finally {
    clearTimeout(timeout);
    signal?.removeEventListener("abort", onAbort);
    noteRequestEnd(reachedServer);
  }
}

/**
 * Turn the error envelope into an ApiError.
 *
 * Falls back to a status-derived code only when the envelope is missing,
 * which should not happen -- the backend routes every failure, including
 * FastAPI's own validation errors, through one handler.
 */
function toApiError(payload: unknown, status: number): ApiError {
  const parsed = errorEnvelopeSchema.safeParse(payload);
  if (parsed.success) {
    const { code, message, details } = parsed.data.error;
    return new ApiError(code as AnyErrorCode, message, status, details ?? null);
  }

  const fallback: Record<number, ErrorCode> = {
    401: "UNAUTHENTICATED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",
    422: "VALIDATION_ERROR",
    500: "INTERNAL_ERROR",
  };
  return new ApiError(
    fallback[status] ?? "INTERNAL_ERROR",
    "Something went wrong.",
    status,
  );
}

/* -------------------------------------------------------------- shortcuts */

export const api = {
  get: <T>(path: string, schema: z.ZodType<T>, options?: RequestOptions) =>
    request(path, schema, { ...options, method: "GET" }),

  post: <T>(
    path: string,
    schema: z.ZodType<T>,
    body?: unknown,
    options?: RequestOptions,
  ) => request(path, schema, { ...options, method: "POST", body }),

  patch: <T>(
    path: string,
    schema: z.ZodType<T>,
    body?: unknown,
    options?: RequestOptions,
  ) => request(path, schema, { ...options, method: "PATCH", body }),

  delete: <T>(path: string, schema: z.ZodType<T>, options?: RequestOptions) =>
    request(path, schema, { ...options, method: "DELETE" }),
};
