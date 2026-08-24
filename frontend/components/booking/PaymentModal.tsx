"use client";

import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Countdown } from "@/components/ui/Countdown";
import { Modal } from "@/components/ui/Modal";
import { formatMoney } from "@/lib/seatmap";
import { cn } from "@/lib/cn";

/**
 * Mock payment.
 *
 * FRONTEND ONLY. There is no payment endpoint, no transaction record and no
 * field anywhere that says a payment happened -- POST /api/holds/{id}/confirm
 * is still the single call that creates the booking, unchanged. This screen
 * exists so the flow reads like a booking product rather than stopping short.
 *
 * Deliberately NO card fields. A form that accepts a card number and does
 * nothing with it is worse than no form: it reads as unfinished, invites
 * someone to type a real number into a demo, and would be the one part of
 * this build that lies about what it does. A method picker plus a pay button
 * says "this step is understood and intentionally not implemented", which is
 * the honest thing to communicate.
 *
 * The countdown is the SAME component reading the SAME expires_at as
 * checkout. The hold does not pause because a payment sheet is open, and
 * pretending otherwise would let someone sit here past their own deadline.
 */

const METHODS = [
  { id: "card", label: "Card", detail: "Visa, Mastercard, RuPay" },
  { id: "upi", label: "UPI", detail: "GPay, PhonePe, Paytm" },
  { id: "netbanking", label: "Net banking", detail: "All major banks" },
] as const;

type MethodId = (typeof METHODS)[number]["id"];

/** Long enough to read as work, short enough not to burn the hold. */
const PROCESSING_MS = 1200;

export function PaymentModal({
  open,
  onClose,
  total,
  expiresAt,
  expired,
  onExpire,
  onPaid,
}: {
  open: boolean;
  onClose: () => void;
  total: number;
  expiresAt: string;
  expired: boolean;
  onExpire: () => void;
  /** Runs the real confirm. Resolves when the booking exists. */
  onPaid: () => Promise<void>;
}) {
  const [method, setMethod] = useState<MethodId>("card");
  const [processing, setProcessing] = useState(false);

  const pay = async () => {
    if (expired) return;
    setProcessing(true);
    // The pause is theatre and is labelled as such; the confirm that follows
    // is entirely real.
    await new Promise((resolve) => setTimeout(resolve, PROCESSING_MS));
    try {
      await onPaid();
    } finally {
      setProcessing(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={processing ? () => {} : onClose}
      title="Payment"
      dismissible={!processing}
      size="md"
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={processing}>
            Back
          </Button>
          <Button
            onClick={() => void pay()}
            loading={processing}
            disabled={expired}
            className="min-w-[9rem]"
          >
            {expired ? "Hold expired" : `Pay ${formatMoney(total)}`}
          </Button>
        </>
      }
    >
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border bg-surface px-4 py-3">
        <div>
          <p className="text-[11px] uppercase tracking-[0.12em] text-muted">
            Amount due
          </p>
          <p className="mt-0.5 font-display text-2xl tabular-nums text-accent">
            {formatMoney(total)}
          </p>
        </div>
        <div className="text-right">
          <p className="text-[11px] uppercase tracking-[0.12em] text-muted">
            {expired ? "Hold expired" : "Seats held for"}
          </p>
          <Countdown
            expiresAt={expiresAt}
            warnAtSeconds={60}
            className="mt-0.5 text-xl"
            onExpire={onExpire}
          />
        </div>
      </div>

      <fieldset className="mt-5" disabled={processing || expired}>
        <legend className="mb-2 text-[13px] text-muted">Payment method</legend>
        <div className="space-y-2">
          {METHODS.map((option) => {
            const selected = method === option.id;
            return (
              <label
                key={option.id}
                className={cn(
                  "flex cursor-pointer items-center gap-3 rounded-lg border px-4 py-3 transition-colors duration-150",
                  selected
                    ? "border-accent bg-accent-soft"
                    : "border-border bg-surface hover:border-border-strong",
                  (processing || expired) && "cursor-not-allowed opacity-60",
                )}
              >
                <input
                  type="radio"
                  name="payment-method"
                  value={option.id}
                  checked={selected}
                  onChange={() => setMethod(option.id)}
                  className="sr-only"
                />
                <span
                  aria-hidden="true"
                  className={cn(
                    "grid h-4 w-4 shrink-0 place-items-center rounded-full border transition-colors",
                    selected ? "border-accent" : "border-border-strong",
                  )}
                >
                  {selected && (
                    <span className="h-2 w-2 rounded-full bg-accent" />
                  )}
                </span>
                <span className="min-w-0">
                  <span
                    className={cn(
                      "block text-sm",
                      selected ? "text-accent" : "text-text",
                    )}
                  >
                    {option.label}
                  </span>
                  <span className="block text-[12px] text-muted">
                    {option.detail}
                  </span>
                </span>
              </label>
            );
          })}
        </div>
      </fieldset>

      {expired ? (
        <p role="alert" className="mt-4 text-[13px] text-danger">
          Your hold expired. The seats went back on sale and nothing was
          charged.
        </p>
      ) : (
        <p className="mt-4 text-center text-[12px] text-muted">
          Demo payment &mdash; no real transaction is processed.
        </p>
      )}
    </Modal>
  );
}
