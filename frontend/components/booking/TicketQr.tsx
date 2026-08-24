"use client";

import { useEffect, useRef, useState } from "react";
import QRCode from "qrcode";

/**
 * The ticket QR.
 *
 * Encodes a URL to /checkin/{reference}.{signature}, so a phone camera offers
 * to open it rather than shrugging at a string it cannot use. The signed
 * credential inside is what the backend verifies; a raw reference on its own
 * is deliberately NOT enough to admit anyone, because the signature is an
 * HMAC the server recomputes.
 *
 * Rendered client-side rather than fetched as an image, so the ticket appears
 * instantly from data already in hand and works with no further requests.
 */
export function TicketQr({
  reference,
  signature,
  size = 176,
}: {
  reference: string;
  signature: string | null;
  size?: number;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!signature || !canvasRef.current) return;
    let cancelled = false;

    // The SAME URL the backend encodes into the emailed ticket. Built from
    // this page's own origin rather than a configured base, so it is correct
    // by construction wherever the frontend is served from -- and the
    // check-in endpoint accepts the bare credential too, so the two forms
    // cannot drift into disagreeing about which ticket they mean.
    const payload = `${window.location.origin}/checkin/${reference}.${signature}`;

    QRCode.toCanvas(canvasRef.current, payload, {
      width: size,
      margin: 1,
      color: {
        // Ivory on obsidian, so the code belongs to the interface rather than
        // punching a white square into a dark page. Scanners cope with
        // inverted codes, and the contrast ratio here is well above what they
        // need.
        dark: "#F5F3EEFF",
        light: "#0D0D0FFF",
      },
      errorCorrectionLevel: "M",
    }).catch(() => {
      if (!cancelled) setFailed(true);
    });

    return () => {
      cancelled = true;
    };
  }, [reference, signature, size]);

  // No signature means a cancelled booking, or one whose QR was invalidated.
  // The reference alone still identifies the booking at the counter.
  if (!signature || failed) {
    return (
      <div
        className="grid place-items-center rounded-xl border border-dashed border-border bg-surface px-6 text-center"
        style={{ width: size, height: size }}
      >
        <div>
          <p className="font-display text-lg tracking-wider text-text">
            {reference}
          </p>
          <p className="mt-1 text-[11px] leading-snug text-muted">
            {signature ? "Could not draw the code" : "No ticket code"}
          </p>
        </div>
      </div>
    );
  }

  return (
    <canvas
      ref={canvasRef}
      width={size}
      height={size}
      className="rounded-xl border border-border"
      aria-label={`Ticket QR code for booking ${reference}`}
      role="img"
    />
  );
}
