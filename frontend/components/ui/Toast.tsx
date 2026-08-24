"use client";

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";
import { cn } from "@/lib/cn";
import { isApiError } from "@/lib/api";
import { useMounted } from "@/lib/use-mounted";

export type ToastTone = "info" | "success" | "error";

export type Toast = {
  id: string;
  tone: ToastTone;
  title: string;
  description?: string;
  /** 0 keeps it up until dismissed. */
  durationMs: number;
};

type ToastInput = Omit<Partial<Toast>, "id"> & { title: string };

type ToastApi = {
  show: (toast: ToastInput) => string;
  success: (title: string, description?: string) => string;
  error: (title: string, description?: string) => string;
  /** Renders any thrown value, using ApiError's message when it is one. */
  fromError: (error: unknown, fallback?: string) => string;
  dismiss: (id: string) => void;
};

const ToastContext = createContext<ToastApi | null>(null);

export function useToast(): ToastApi {
  const context = useContext(ToastContext);
  if (!context) throw new Error("useToast must be used inside <ToastProvider>");
  return context;
}

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const timers = useRef(new Map<string, ReturnType<typeof setTimeout>>());

  const dismiss = useCallback((id: string) => {
    const timer = timers.current.get(id);
    if (timer) {
      clearTimeout(timer);
      timers.current.delete(id);
    }
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  const show = useCallback(
    (input: ToastInput) => {
      const id =
        typeof crypto !== "undefined" && "randomUUID" in crypto
          ? crypto.randomUUID()
          : `t-${Date.now()}-${Math.random()}`;

      const toast: Toast = {
        id,
        tone: input.tone ?? "info",
        title: input.title,
        description: input.description,
        durationMs: input.durationMs ?? (input.tone === "error" ? 7000 : 4500),
      };

      // Cap the stack. Beyond a few, they cover the content they describe.
      setToasts((current) => [...current.slice(-3), toast]);

      if (toast.durationMs > 0) {
        timers.current.set(
          id,
          setTimeout(() => dismiss(id), toast.durationMs),
        );
      }
      return id;
    },
    [dismiss],
  );

  const api = useMemo<ToastApi>(
    () => ({
      show,
      dismiss,
      success: (title, description) => show({ tone: "success", title, description }),
      error: (title, description) => show({ tone: "error", title, description }),
      fromError: (error, fallback = "Something went wrong.") => {
        // ApiError already carries a message written for a person; anything
        // else is an internal failure and must not have its text shown.
        const title = isApiError(error) ? error.message : fallback;
        const description =
          isApiError(error) && error.correlationId
            ? `Reference ${error.correlationId}`
            : undefined;
        return show({ tone: "error", title, description });
      },
    }),
    [show, dismiss],
  );

  return (
    <ToastContext.Provider value={api}>
      {children}
      <ToastViewport toasts={toasts} onDismiss={dismiss} />
    </ToastContext.Provider>
  );
}

const toneStyles: Record<ToastTone, string> = {
  info: "border-border",
  success: "border-success/30",
  error: "border-danger/30",
};

const toneAccent: Record<ToastTone, string> = {
  info: "bg-muted",
  success: "bg-success",
  error: "bg-danger",
};

function ToastViewport({
  toasts,
  onDismiss,
}: {
  toasts: Toast[];
  onDismiss: (id: string) => void;
}) {
  // Gated on mount, not on `typeof document`: the latter renders nothing on
  // the server and the portal on the client's first render, which is a
  // hydration mismatch that throws away the whole tree.
  const mounted = useMounted();
  if (!mounted) return null;

  return createPortal(
    <div
      className="pointer-events-none fixed inset-x-0 bottom-0 z-[60] flex flex-col items-center gap-2 p-4 sm:items-end sm:p-6"
      role="region"
      aria-label="Notifications"
    >
      {toasts.map((toast) => (
        <div
          key={toast.id}
          role={toast.tone === "error" ? "alert" : "status"}
          className={cn(
            "glass pointer-events-auto relative w-full max-w-sm overflow-hidden rounded-xl pl-4 pr-3 py-3.5",
            "animate-[essemble-toast-in_200ms_var(--ease-out-soft)]",
            toneStyles[toast.tone],
          )}
        >
          <span
            aria-hidden="true"
            className={cn(
              "absolute inset-y-0 left-0 w-[3px]",
              toneAccent[toast.tone],
            )}
          />
          <div className="flex items-start gap-3">
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-text">{toast.title}</p>
              {toast.description && (
                <p className="mt-0.5 text-[13px] leading-relaxed text-muted">
                  {toast.description}
                </p>
              )}
            </div>
            <button
              type="button"
              onClick={() => onDismiss(toast.id)}
              aria-label="Dismiss"
              className="-mr-1 grid h-7 w-7 shrink-0 place-items-center rounded-md text-muted transition-colors hover:bg-surface-2 hover:text-text"
            >
              <svg viewBox="0 0 12 12" className="h-3 w-3" aria-hidden="true">
                <path
                  d="M2 2l8 8M10 2L2 10"
                  stroke="currentColor"
                  strokeWidth="1.6"
                  strokeLinecap="round"
                />
              </svg>
            </button>
          </div>
        </div>
      ))}
    </div>,
    document.body,
  );
}
