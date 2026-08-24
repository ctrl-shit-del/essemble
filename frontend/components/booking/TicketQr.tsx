"use client";

import { useEffect, useRef, useState } from "react";
import QRCode from "qrcode";

/**
 * The ticket QR.
 *
 * The payload is `reference.qr_signature` -- exactly what the door scanner
 * expects, and exactly what the backend's check-in endpoint verifies. A raw
 * reference on its own is deliberately NOT enough to admit anyone: the
 * signature is an HMAC the server recomputes, which is why a screenshot of
 * the reference alone cannot become a ticket.
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

    QRCode.toCanvas(canvasRef.current, `${reference}.${signature}`, {
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
