"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Html5Qrcode } from "html5-qrcode";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { CheckinResult } from "@/components/checkin/CheckinResult";
import {
  outcomeFromError,
  verifyTicket,
  type CheckinOutcome,
} from "@/lib/checkin";
import { cn } from "@/lib/cn";

/**
 * The door scanner.
 *
 * Two rules shape this, both learned from what a real door does:
 *
 * 1. NEVER auto-resume after a result. Staff have to read the verdict, and a
 *    viewfinder that immediately starts hunting again will scan the next
 *    person in the queue while the first is still being looked at. "Scan
 *    next" is a deliberate act.
 *
 * 2. Debounce identical decodes. A ticket held still in frame decodes many
 *    times a second, and without this every one of them would POST. The
 *    endpoint is idempotent -- the second call answers ALREADY_USED -- but
 *    the screen would flip from Admit to Already used while the holder was
 *    still walking through, which is exactly the wrong thing to show.
 */

const SCAN_REGION_ID = "essemble-scan-region";
const DUPLICATE_WINDOW_MS = 3000;

type CameraState = "starting" | "scanning" | "paused" | "denied" | "unavailable";

export default function ScannerPage() {
  const scannerRef = useRef<Html5Qrcode | null>(null);
  const lastDecode = useRef<{ payload: string; at: number } | null>(null);
  // Read inside the decode callback, which html5-qrcode captures once.
  const busyRef = useRef(false);

  const [camera, setCamera] = useState<CameraState>("starting");
  const [outcome, setOutcome] = useState<CheckinOutcome | null>(null);
  const [checking, setChecking] = useState(false);
  const [admitted, setAdmitted] = useState(0);
  const [manual, setManual] = useState("");

  /* ------------------------------------------------------------- verify */

  const submit = useCallback(async (payload: string) => {
    busyRef.current = true;
    setChecking(true);
    try {
      const ticket = await verifyTicket(payload);
      setOutcome({ kind: "valid", ticket });
      // Only a genuine admission counts. An already-used scan is not a
      // person going through the door.
      setAdmitted((count) => count + 1);
    } catch (error) {
      setOutcome(outcomeFromError(error, payload));
    } finally {
      setChecking(false);
    }
  }, []);

  /* ------------------------------------------------------------- camera */

  const stop = useCallback(async () => {
    const scanner = scannerRef.current;
    if (!scanner) return;
    try {
      if (scanner.isScanning) await scanner.stop();
    } catch {
      // Already stopped, or the element went away. Nothing to recover.
    }
  }, []);

  const start = useCallback(async () => {
    setCamera("starting");
    try {
      const cameras = await Html5Qrcode.getCameras();
      if (!cameras || cameras.length === 0) {
        setCamera("unavailable");
        return;
      }

      const scanner = scannerRef.current ?? new Html5Qrcode(SCAN_REGION_ID);
      scannerRef.current = scanner;

      await scanner.start(
        // Rear camera where there is one; a phone at a door is held facing
        // the ticket, not the operator.
        { facingMode: "environment" },
        { fps: 10, qrbox: { width: 260, height: 260 } },
        (decoded) => {
          const now = Date.now();
          const previous = lastDecode.current;
          // Same ticket still in frame: ignore rather than re-post.
          if (
            previous &&
            previous.payload === decoded &&
            now - previous.at < DUPLICATE_WINDOW_MS
          ) {
            return;
          }
          if (busyRef.current) return;
          lastDecode.current = { payload: decoded, at: now };
          void stop().then(() => setCamera("paused"));
          void submit(decoded);
        },
        () => {
          // Fires constantly for every frame without a code. Not an error.
        },
      );
      setCamera("scanning");
    } catch (error) {
      const message = String(error);
      setCamera(
        /permission|denied|NotAllowed/i.test(message) ? "denied" : "unavailable",
      );
    }
  }, [stop, submit]);

  useEffect(() => {
    void start();
    return () => {
      // Release the camera on unmount, or the indicator light stays on and
      // the next page cannot open it.
      void stop().then(() => {
        try {
          scannerRef.current?.clear();
        } catch {
          // Element already unmounted.
        }
        scannerRef.current = null;
      });
    };
    // Mount only: start/stop are stable and re-running would restart the
    // camera mid-scan.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const scanNext = useCallback(() => {
    setOutcome(null);
    busyRef.current = false;
    lastDecode.current = null;
    void start();
  }, [start]);

  const submitManual = useCallback(
    (event: React.FormEvent) => {
      event.preventDefault();
      const value = manual.trim();
      if (!value) return;
      setManual("");
      busyRef.current = false;
      void submit(value);
    },
    [manual, submit],
  );

  const liveCamera = camera === "scanning" || camera === "starting";

  return (
    <div className="mx-auto max-w-3xl">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="font-display text-2xl tracking-tight text-text">
            Scanner
          </h1>
          <p className="mt-1 text-[13px] text-muted">
            Point the camera at a ticket QR, or type a reference below.
          </p>
        </div>
        <div className="text-right">
          <p className="text-[11px] uppercase tracking-[0.14em] text-muted">
            Admitted this session
          </p>
          <p className="font-display text-3xl tabular-nums text-accent">
            {admitted}
          </p>
        </div>
      </div>

      {/* Viewfinder. Kept mounted at all times: html5-qrcode attaches to this
          element by id, and unmounting it between scans would mean tearing
          the scanner down and rebuilding it on every ticket. */}
      <div className="mt-6 overflow-hidden rounded-xl border border-border bg-surface">
        <div className="relative">
          <div
            id={SCAN_REGION_ID}
            className={cn(
              "mx-auto w-full [&_video]:!w-full [&_video]:!rounded-none",
              liveCamera ? "block" : "hidden",
            )}
          />

          {camera === "scanning" && (
            <div
              aria-hidden="true"
              className="pointer-events-none absolute inset-0 grid place-items-center"
            >
              <div className="relative h-[260px] w-[260px]">
                {/* Corner brackets rather than a full box: they mark the
                    region without covering the thing being read. */}
                {[
                  "left-0 top-0 border-l-2 border-t-2 rounded-tl-lg",
                  "right-0 top-0 border-r-2 border-t-2 rounded-tr-lg",
                  "left-0 bottom-0 border-l-2 border-b-2 rounded-bl-lg",
                  "right-0 bottom-0 border-r-2 border-b-2 rounded-br-lg",
                ].map((corner) => (
                  <span
                    key={corner}
                    className={cn("absolute h-8 w-8 border-accent", corner)}
                  />
                ))}
              </div>
            </div>
          )}

          {camera === "starting" && (
            <div className="grid h-64 place-items-center">
              <p className="text-[13px] text-muted">Starting the camera…</p>
            </div>
          )}

          {(camera === "denied" || camera === "unavailable") && (
            <div className="grid place-items-center px-6 py-10 text-center">
              <div>
                <p className="font-display text-lg text-text">
                  {camera === "denied"
                    ? "Camera permission refused"
                    : "No camera available"}
                </p>
                <p className="mx-auto mt-1.5 max-w-sm text-[13px] leading-relaxed text-muted">
                  {camera === "denied"
                    ? "Allow camera access in your browser settings, or type the reference below — check-in works either way."
                    : "This device has no camera the browser can use. Type the reference below instead."}
                </p>
                {camera === "denied" && (
                  <Button variant="ghost" className="mt-4" onClick={() => void start()}>
                    Try the camera again
                  </Button>
                )}
              </div>
            </div>
          )}

          {camera === "paused" && !checking && (
            <div className="grid h-32 place-items-center">
              <p className="text-[13px] text-muted">Camera paused</p>
            </div>
          )}

          {checking && (
            <div className="grid h-32 place-items-center">
              <p className="text-[13px] text-muted">Checking ticket…</p>
            </div>
          )}
        </div>
      </div>

      {outcome && (
        <div className="mt-5">
          <CheckinResult outcome={outcome} compact />
          <Button size="lg" fullWidth className="mt-4" onClick={scanNext}>
            Scan next
          </Button>
        </div>
      )}

      {/* The fallback that makes this usable on a laptop, and the reason a
          dead camera is an inconvenience rather than a blocked door. */}
      <form
        onSubmit={submitManual}
        className="mt-6 rounded-xl border border-border bg-surface p-5"
      >
        <div className="flex items-center gap-2">
          <h2 className="font-display text-base text-text">Manual entry</h2>
          <Badge tone="outline">Fallback</Badge>
        </div>
        <p className="mt-1 text-[13px] leading-relaxed text-muted">
          Paste the scanned link, or type the full ticket code from the
          customer&rsquo;s confirmation.
        </p>
        <div className="mt-3 flex gap-2">
          <Input
            value={manual}
            onChange={(event) => setManual(event.target.value)}
            placeholder="ESB-XXXXXX.a1b2c3d4e5f6a7b8"
            aria-label="Ticket code"
            className="font-mono"
          />
          <Button type="submit" loading={checking} disabled={!manual.trim()}>
            Check
          </Button>
        </div>
        <p className="mt-2 text-[12px] leading-relaxed text-muted">
          A booking reference on its own is deliberately not enough — the
          signed code is what proves the ticket is genuine.
        </p>
      </form>
    </div>
  );
}
