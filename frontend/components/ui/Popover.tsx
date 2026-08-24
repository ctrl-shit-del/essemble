"use client";

import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useMounted } from "@/lib/use-mounted";
import { cn } from "@/lib/cn";

/**
 * Glass panel anchored to a trigger.
 *
 * PORTALLED TO document.body, and positioned from the trigger's bounding box
 * rather than by CSS `absolute` inside the trigger's own container.
 *
 * That is not over-engineering, it is the fix for a real bug: the navbar
 * wraps its right-hand tools in `overflow-hidden` so the links can collapse
 * into the search field, and an absolutely-positioned child of that wrapper
 * gets clipped out of existence -- the panel was rendering at y = -59, fully
 * open in the DOM and invisible on screen. Any popover living inside a
 * clipping or transformed ancestor has the same problem, so the component
 * refuses to depend on its ancestors at all.
 *
 * Dismissal is the other thing that matters: outside pointer-down and Escape
 * both close it, and Escape returns focus to the trigger rather than dropping
 * it on the body.
 */
export function Popover({
  open,
  onClose,
  trigger,
  children,
  align = "end",
  label,
  className,
}: {
  open: boolean;
  onClose: () => void;
  trigger: (props: {
    id: string;
    "aria-expanded": boolean;
    "aria-haspopup": "menu";
  }) => React.ReactNode;
  children: React.ReactNode;
  align?: "start" | "end";
  label: string;
  className?: string;
}) {
  const anchorRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const triggerId = useId();
  const mounted = useMounted();
  const [position, setPosition] = useState<{ top: number; left: number } | null>(
    null,
  );

  const place = useCallback(() => {
    const anchor = anchorRef.current?.getBoundingClientRect();
    if (!anchor) return;
    const width = panelRef.current?.offsetWidth ?? 240;
    const gap = 8;
    const margin = 12;

    const preferred =
      align === "end" ? anchor.right - width : anchor.left;
    // Keep the panel on screen whatever the trigger is doing near an edge.
    const left = Math.min(
      Math.max(margin, preferred),
      window.innerWidth - width - margin,
    );

    setPosition({ top: anchor.bottom + gap, left });
  }, [align]);

  // Before paint, so the panel never flashes at the wrong coordinates.
  useLayoutEffect(() => {
    if (open) place();
  }, [open, place]);

  useEffect(() => {
    if (!open) return;

    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node;
      if (anchorRef.current?.contains(target)) return;
      if (panelRef.current?.contains(target)) return;
      onClose();
    };

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        onClose();
        anchorRef.current?.querySelector<HTMLElement>("button")?.focus();
        return;
      }
      if (event.key !== "Tab") return;

      const focusable = panelRef.current?.querySelectorAll<HTMLElement>(
        'a[href],button:not([disabled]),[tabindex]:not([tabindex="-1"])',
      );
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

    // A fixed panel does not follow its anchor on its own.
    const reposition = () => place();
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown, true);
    window.addEventListener("resize", reposition);
    window.addEventListener("scroll", reposition, true);

    const raf = requestAnimationFrame(() => {
      place();
      panelRef.current
        ?.querySelector<HTMLElement>("a[href],button:not([disabled])")
        ?.focus();
    });

    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown, true);
      window.removeEventListener("resize", reposition);
      window.removeEventListener("scroll", reposition, true);
      cancelAnimationFrame(raf);
    };
  }, [open, onClose, place]);

  return (
    <div ref={anchorRef} className="relative">
      {trigger({ id: triggerId, "aria-expanded": open, "aria-haspopup": "menu" })}

      {open &&
        mounted &&
        createPortal(
          <div
            ref={panelRef}
            role="menu"
            aria-label={label}
            aria-labelledby={triggerId}
            style={{
              top: position?.top ?? 0,
              left: position?.left ?? 0,
              // Invisible until measured, so it cannot flash top-left.
              visibility: position ? "visible" : "hidden",
            }}
            className={cn(
              "glass fixed z-[60] overflow-hidden rounded-xl shadow-2xl",
              "animate-[essemble-fade-in_150ms_var(--ease-out-soft)]",
              className,
            )}
          >
            {children}
          </div>,
          document.body,
        )}
    </div>
  );
}

export function PopoverHeader({
  title,
  subtitle,
}: {
  title: string;
  subtitle?: string;
}) {
  return (
    <div className="px-3.5 py-3">
      <p className="truncate text-sm text-text">{title}</p>
      {subtitle && (
        <p className="mt-0.5 truncate text-[11px] uppercase tracking-[0.12em] text-accent">
          {subtitle}
        </p>
      )}
    </div>
  );
}

export function PopoverDivider() {
  return <div aria-hidden="true" className="h-px bg-border" />;
}

const itemStyles =
  "flex w-full items-center justify-between gap-3 px-3.5 py-2.5 text-left " +
  "text-[13px] text-muted transition-colors hover:bg-surface-2 hover:text-text " +
  "focus-visible:bg-surface-2 focus-visible:text-text";

export function PopoverItem({
  children,
  onClick,
  trailing,
}: {
  children: React.ReactNode;
  onClick: () => void;
  trailing?: React.ReactNode;
}) {
  return (
    <button type="button" role="menuitem" onClick={onClick} className={itemStyles}>
      <span>{children}</span>
      {trailing}
    </button>
  );
}

export { itemStyles as popoverItemStyles };
