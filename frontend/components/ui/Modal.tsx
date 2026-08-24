"use client";

import { useCallback, useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { cn } from "@/lib/cn";
import { useMounted } from "@/lib/use-mounted";

/**
 * Glass dialog. One of the five places glass is allowed.
 *
 * Hand-built rather than pulled from a library: the behaviour that actually
 * matters here is focus containment, restoring focus on close, and locking
 * the background scroll without the page jumping as the scrollbar goes away.
 */
export type ModalProps = {
  open: boolean;
  onClose: () => void;
  title?: string;
  description?: string;
  children: React.ReactNode;
  footer?: React.ReactNode;
  size?: "sm" | "md" | "lg";
  /** Set false for a decision the user must make explicitly. */
  dismissible?: boolean;
};

const sizes = {
  sm: "max-w-sm",
  md: "max-w-lg",
  lg: "max-w-2xl",
};

const FOCUSABLE =
  'a[href],button:not([disabled]),textarea:not([disabled]),input:not([disabled]),select:not([disabled]),[tabindex]:not([tabindex="-1"])';

export function Modal({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  size = "md",
  dismissible = true,
}: ModalProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  const restoreFocusTo = useRef<HTMLElement | null>(null);
  // Same reason as ToastViewport: a portal must not appear on the client's
  // first render if the server did not send it.
  const mounted = useMounted();

  const handleClose = useCallback(() => {
    if (dismissible) onClose();
  }, [dismissible, onClose]);

  useEffect(() => {
    if (!open) return;

    restoreFocusTo.current = document.activeElement as HTMLElement | null;

    // Compensate for the vanishing scrollbar, or the page shifts sideways
    // the moment the dialog opens.
    const scrollbar = window.innerWidth - document.documentElement.clientWidth;
    const { overflow, paddingRight } = document.body.style;
    document.body.style.overflow = "hidden";
    if (scrollbar > 0) document.body.style.paddingRight = `${scrollbar}px`;

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        handleClose();
        return;
      }
      if (event.key !== "Tab") return;

      const focusable = panelRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE);
      if (!focusable || focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];

      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", onKeyDown, true);
    // After paint, so the element exists to receive focus.
    const raf = requestAnimationFrame(() => {
      const focusable = panelRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE);
      (focusable?.[0] ?? panelRef.current)?.focus();
    });

    return () => {
      document.removeEventListener("keydown", onKeyDown, true);
      cancelAnimationFrame(raf);
      document.body.style.overflow = overflow;
      document.body.style.paddingRight = paddingRight;
      restoreFocusTo.current?.focus?.();
    };
  }, [open, handleClose]);

  if (!open || !mounted) return null;

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-end justify-center p-4 sm:items-center"
      role="presentation"
    >
      <div
        className="absolute inset-0 bg-bg/70 backdrop-blur-[2px]"
        onClick={handleClose}
        aria-hidden="true"
      />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        aria-describedby={description ? "essemble-modal-desc" : undefined}
        tabIndex={-1}
        className={cn(
          "glass relative w-full rounded-2xl shadow-2xl outline-none",
          "animate-[essemble-fade-in_180ms_var(--ease-out-soft)]",
          sizes[size],
        )}
      >
        {(title || dismissible) && (
          <div className="flex items-start justify-between gap-4 px-6 pt-6">
            <div>
              {title && (
                <h2 className="font-display text-xl leading-tight text-text">
                  {title}
                </h2>
              )}
              {description && (
                <p
                  id="essemble-modal-desc"
                  className="mt-1.5 text-sm leading-relaxed text-muted"
                >
                  {description}
                </p>
              )}
            </div>
            {dismissible && (
              <button
                type="button"
                onClick={onClose}
                aria-label="Close"
                className="-mr-2 -mt-2 grid h-9 w-9 shrink-0 place-items-center rounded-lg text-muted transition-colors hover:bg-surface-2 hover:text-text"
              >
                <svg viewBox="0 0 14 14" className="h-4 w-4" aria-hidden="true">
                  <path
                    d="M2 2l10 10M12 2L2 12"
                    stroke="currentColor"
                    strokeWidth="1.6"
                    strokeLinecap="round"
                  />
                </svg>
              </button>
            )}
          </div>
        )}

        <div className="px-6 py-5">{children}</div>

        {footer && (
          <div className="flex items-center justify-end gap-3 border-t border-border px-6 py-4">
            {footer}
          </div>
        )}
      </div>
    </div>,
    document.body,
  );
}
