/**
 * Every error code, in words a customer can act on.
 *
 * A raw code must never reach a person. `SEAT_UNAVAILABLE` means nothing to
 * someone who just lost a seat; "Those seats were taken while you were
 * choosing" tells them what happened and what to do next.
 *
 * The backend's own `message` is written for a person too, and is often more
 * specific than anything generic here -- it names the cutoff in minutes, the
 * seat limit, the show's status. So the rule is: prefer the server's sentence
 * when it has one, and fall back to these when it does not, or when the
 * context needs a different framing than the API can know about.
 *
 * `context` exists for exactly that. HOLD_EXPIRED during checkout is a
 * different sentence from HOLD_EXPIRED on the seat map, because the person is
 * somewhere else and needs a different next step.
 */

import { isApiError } from "./api";
import type { AnyErrorCode } from "./types";

export type ErrorContext =
  | "seatmap"
  | "checkout"
  | "waitlist"
  | "offer"
  | "cancel"
  | "auth"
  | "generic";

type Copy = { title: string; detail?: string };

const GENERIC: Record<AnyErrorCode, Copy> = {
  SEAT_UNAVAILABLE: {
    title: "Those seats were taken",
    detail: "Someone else got there first. Pick different seats and try again.",
  },
  HOLD_EXPIRED: {
    title: "Your hold expired",
    detail: "The seats were released so other people could book them.",
  },
  HOLD_LIMIT_EXCEEDED: {
    title: "Too many seats",
    detail: "There is a limit on how many seats one booking can cover.",
  },
  OFFER_EXPIRED: {
    title: "This offer has lapsed",
    detail: "The seats have gone to the next person on the waitlist.",
  },
  NOT_SOLD_OUT: {
    title: "Seats are still available",
    detail: "You can book directly instead of joining the waitlist.",
  },
  INVALID_SIGNATURE: {
    title: "That ticket could not be verified",
    detail: "The QR code is not valid for this booking.",
  },
  ALREADY_USED: {
    title: "This ticket has already been used",
    detail: "It was scanned at the door earlier.",
  },
  CONFLICT: { title: "That is not possible right now" },
  FORBIDDEN: {
    title: "Not yours to access",
    detail: "This belongs to a different account.",
  },
  NOT_FOUND: { title: "Not found" },
  VALIDATION_ERROR: { title: "Check the details and try again" },
  UNAUTHENTICATED: {
    title: "Please sign in",
    detail: "Your session has ended.",
  },
  INTERNAL_ERROR: {
    title: "Something went wrong on our side",
    detail: "It has been logged. Please try again in a moment.",
  },
  NETWORK_ERROR: {
    title: "Could not reach the server",
    detail: "Check your connection and try again.",
  },
  TIMEOUT: {
    title: "The server took too long",
    detail: "It may be starting up. Try again in a moment.",
  },
  MALFORMED_RESPONSE: {
    title: "Unexpected response from the server",
    detail: "Please try again.",
  },
};

/** Overrides where the same code means something different by location. */
const BY_CONTEXT: Partial<Record<ErrorContext, Partial<Record<AnyErrorCode, Copy>>>> = {
  checkout: {
    HOLD_EXPIRED: {
      title: "Your hold expired during checkout",
      detail:
        "No booking was made and you have not been charged. The seats are back on the map.",
    },
    SEAT_UNAVAILABLE: {
      title: "Those seats are no longer held for you",
      detail: "Start again from the seat map.",
    },
  },
  seatmap: {
    HOLD_EXPIRED: {
      title: "That hold has already expired",
      detail: "Select your seats again.",
    },
  },
  waitlist: {
    CONFLICT: {
      title: "You are already on this waitlist",
      detail: "Check the Waitlist tab in your profile for your position.",
    },
    NOT_SOLD_OUT: {
      title: "This category has not sold out",
      detail: "Seats are still on the map -- you can book one now.",
    },
    HOLD_LIMIT_EXCEEDED: {
      title: "That is more seats than the waitlist allows",
    },
  },
  offer: {
    OFFER_EXPIRED: {
      title: "This offer has lapsed",
      detail:
        "Offers are time-limited so the seats can move on quickly. They have gone to the next person waiting.",
    },
    FORBIDDEN: {
      title: "This offer was made to someone else",
      detail: "Sign in with the account the offer email was sent to.",
    },
    UNAUTHENTICATED: {
      title: "Sign in to claim these seats",
      detail: "You will come straight back here.",
    },
  },
  cancel: {
    CONFLICT: {
      title: "Too late to cancel",
      detail:
        "Cancellation closes shortly before the show starts, so the seats can be resold in time.",
    },
    FORBIDDEN: {
      title: "That booking is not yours",
    },
  },
};

/**
 * Turn anything thrown into a title and a detail line.
 *
 * `preferServerMessage` is on by default: the API writes its failures for
 * people, and its version usually carries a specific number this file cannot
 * know. It is turned off where the context override is deliberately better.
 */
export function describeError(
  error: unknown,
  context: ErrorContext = "generic",
  options: { preferServerMessage?: boolean } = {},
): Copy {
  const { preferServerMessage = true } = options;

  if (!isApiError(error)) {
    return {
      title: "Something went wrong",
      detail: "Please try again.",
    };
  }

  const override = BY_CONTEXT[context]?.[error.code];
  if (override) return override;

  const base = GENERIC[error.code] ?? { title: "Something went wrong" };

  // The server's sentence wins when it has one, except for INTERNAL_ERROR,
  // where the message is deliberately generic and the detail should carry the
  // correlation id instead.
  if (preferServerMessage && error.message && error.code !== "INTERNAL_ERROR") {
    return { title: base.title, detail: error.message };
  }

  if (error.code === "INTERNAL_ERROR" && error.correlationId) {
    return { ...base, detail: `${base.detail} Reference ${error.correlationId}.` };
  }

  return base;
}

/** Convenience for toast.show({...}). */
export function toastFor(error: unknown, context: ErrorContext = "generic") {
  const { title, detail } = describeError(error, context);
  return { tone: "error" as const, title, description: detail };
}
