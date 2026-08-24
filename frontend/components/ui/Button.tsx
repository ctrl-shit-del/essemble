"use client";

import { forwardRef } from "react";
import { cn } from "@/lib/cn";

type Variant = "primary" | "ghost" | "danger" | "quiet";
type Size = "sm" | "md" | "lg";

export type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  size?: Size;
  /** Shows a spinner and blocks input without changing the button's width. */
  loading?: boolean;
  fullWidth?: boolean;
};

const base =
  "relative inline-flex items-center justify-center gap-2 rounded-lg font-medium " +
  "transition-[background-color,border-color,color,transform,opacity] duration-150 " +
  "select-none whitespace-nowrap active:translate-y-px " +
  "disabled:pointer-events-none disabled:opacity-45";

const variants: Record<Variant, string> = {
  // Amber is the primary CTA and almost nothing else. One per view.
  primary:
    "bg-accent text-bg hover:bg-accent-hover active:bg-accent-press " +
    "shadow-[0_1px_0_rgba(255,255,255,0.18)_inset]",
  ghost:
    "bg-transparent text-text border border-border hover:border-border-strong " +
    "hover:bg-surface-2",
  danger: "bg-danger-soft text-danger border border-danger/25 hover:bg-danger/20",
  // For tertiary actions that should not read as buttons until hovered.
  quiet: "bg-transparent text-muted hover:text-text hover:bg-surface-2",
};

const sizes: Record<Size, string> = {
  sm: "h-8 px-3 text-[13px]",
  md: "h-10 px-4 text-sm",
  lg: "h-12 px-6 text-[15px]",
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  function Button(
    {
      variant = "primary",
      size = "md",
      loading = false,
      fullWidth = false,
      className,
      children,
      disabled,
      type = "button",
      ...rest
    },
    ref,
  ) {
    return (
      <button
        ref={ref}
        type={type}
        disabled={disabled || loading}
        aria-busy={loading || undefined}
        className={cn(
          base,
          variants[variant],
          sizes[size],
          fullWidth && "w-full",
          className,
        )}
        {...rest}
      >
        {/* The label keeps its space while loading, so the button does not
            resize and shift whatever sits next to it. */}
        <span className={cn("contents", loading && "invisible")}>{children}</span>
        {loading && (
          <span
            className="absolute inset-0 grid place-items-center"
            aria-hidden="true"
          >
            <Spinner />
          </span>
        )}
      </button>
    );
  },
);

function Spinner() {
  return (
    <svg viewBox="0 0 16 16" className="h-4 w-4 animate-spin" fill="none">
      <circle
        cx="8"
        cy="8"
        r="6.5"
        stroke="currentColor"
        strokeOpacity="0.25"
        strokeWidth="2"
      />
      <path
        d="M14.5 8A6.5 6.5 0 0 0 8 1.5"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
      />
    </svg>
  );
}
