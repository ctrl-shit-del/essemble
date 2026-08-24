"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import { Brand } from "@/components/shell/Brand";
import { Button } from "@/components/ui/Button";
import { Skeleton } from "@/components/ui/Skeleton";
import { CheckinResult } from "@/components/checkin/CheckinResult";
import { useAuth } from "@/components/auth/AuthProvider";
import {
  outcomeFromError,
  referenceFromPayload,
  verifyTicket,
  type CheckinOutcome,
} from "@/lib/checkin";

/**
 * Where a phone camera lands.
 *
 * The QR encodes {APP_BASE_URL}/checkin/{reference}.{signature}, so scanning
 * a ticket with the stock camera app offers to open this page. That is the
 * whole reason the payload became a URL -- bare text gave the camera nothing
 * to do with it.
 *
 * Deliberately OUTSIDE the customer and admin shells: this is a single-
 * purpose screen someone looks at for two seconds, and a navbar would only
 * add things to tap by accident while holding a queue.
 *
 * PUBLIC, because anyone can scan a QR -- including the ticket holder, out of
 * curiosity. What it shows them is the reference and nothing else. Check-in
 * itself needs an admin, and the endpoint enforces that regardless of what
 * this page renders.
 */
export default function CheckinPage({
  params,
}: {
  params: Promise<{ payload: string }>;
}) {
  const { payload } = use(params);
  const decoded = decodeURIComponent(payload);
  const { user, loading: authLoading } = useAuth();

  const [outcome, setOutcome] = useState<CheckinOutcome | null>(null);
  const [checking, setChecking] = useState(false);

  const isAdmin = user?.role === "admin";

  useEffect(() => {
    if (authLoading || !isAdmin || outcome || checking) return;

    let cancelled = false;
    setChecking(true);

    // Verify on arrival. Staff scanned it to get here; making them press a
    // second button would be a step with no decision in it.
    verifyTicket(decoded)
      .then((ticket) => {
        if (!cancelled) setOutcome({ kind: "valid", ticket });
      })
      .catch((error) => {
        if (!cancelled) setOutcome(outcomeFromError(error, decoded));
      })
      .finally(() => {
        if (!cancelled) setChecking(false);
      });

    return () => {
      cancelled = true;
    };
  }, [authLoading, isAdmin, outcome, checking, decoded]);

  const reference = referenceFromPayload(decoded);

  return (
    <div className="min-h-dvh bg-bg px-5 py-8">
      <div className="mx-auto w-full max-w-xl">
        <div className="mb-8 flex items-center justify-between">
          <Brand />
          <span className="text-[11px] uppercase tracking-[0.16em] text-muted">
            Door check-in
          </span>
        </div>

        {authLoading ? (
          <Skeleton className="h-48 w-full rounded-2xl" />
        ) : !isAdmin ? (
          <StaffOnly
            reference={reference}
            payload={payload}
            signedIn={Boolean(user)}
          />
        ) : checking || !outcome ? (
          <Verifying reference={reference} />
        ) : (
          <>
            <CheckinResult outcome={outcome} />
            <div className="mt-6 flex justify-center">
              <Link href="/admin/scanner">
                <Button variant="ghost">Open the scanner</Button>
              </Link>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

/**
 * The anonymous view.
 *
 * Shows the reference and NOTHING else -- not the film, not the seats, not
 * the customer's name. A QR code is on a screen someone can photograph over a
 * shoulder, and this page would otherwise turn that into a readout of who is
 * sitting where.
 */
function StaffOnly({
  reference,
  payload,
  signedIn,
}: {
  reference: string | null;
  payload: string;
  signedIn: boolean;
}) {
  const next = `/checkin/${payload}`;
  return (
    <section className="rounded-2xl border border-border bg-surface px-6 py-8 text-center">
      <p className="text-[11px] uppercase tracking-[0.16em] text-muted">
        Ticket
      </p>
      <p className="mt-2 select-all font-display text-4xl tracking-[0.05em] text-accent">
        {reference ?? "Unrecognised"}
      </p>

      <p className="mx-auto mt-6 max-w-sm text-[15px] leading-relaxed text-text">
        {reference
          ? "This ticket can only be checked in by venue staff."
          : "This does not look like an ESSEMBLE ticket."}
      </p>
      {reference && (
        <p className="mx-auto mt-2 max-w-sm text-[13px] leading-relaxed text-muted">
          {signedIn
            ? "You are signed in, but not as staff for this venue. Ask someone on the door."
            : "Sign in with a venue account to admit this ticket."}
        </p>
      )}

      {reference && !signedIn && (
        <Link href={`/login?next=${encodeURIComponent(next)}`} className="mt-6 inline-block">
          <Button size="lg">Staff sign in</Button>
        </Link>
      )}
    </section>
  );
}

function Verifying({ reference }: { reference: string | null }) {
  return (
    <section className="rounded-2xl border border-border bg-surface px-6 py-10 text-center">
      <p className="text-[11px] uppercase tracking-[0.16em] text-muted">
        Checking
      </p>
      <p className="mt-2 font-display text-3xl tracking-[0.05em] text-text">
        {reference ?? "…"}
      </p>
      <div className="mx-auto mt-6 h-1 w-32 overflow-hidden rounded-full bg-surface-2">
        <div className="h-full w-1/3 animate-[essemble-shimmer_1.1s_infinite] bg-accent" />
      </div>
    </section>
  );
}
