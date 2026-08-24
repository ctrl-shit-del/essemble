"use client";

import { forwardRef, useId } from "react";
import { cn } from "@/lib/cn";

export type InputProps = React.InputHTMLAttributes<HTMLInputElement> & {
  label?: string;
  hint?: string;
  /** Field-level message, typically from an ApiError's fieldErrors. */
  error?: string | null;
  leading?: React.ReactNode;
  trailing?: React.ReactNode;
};

const control =
  "h-11 w-full rounded-lg border bg-surface px-3.5 text-sm text-text " +
  "placeholder:text-muted/60 transition-colors duration-150 " +
  "focus:outline-none focus:border-accent " +
  "disabled:opacity-50 disabled:cursor-not-allowed";

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { label, hint, error, leading, trailing, className, id, ...rest },
  ref,
) {
  const generated = useId();
  const inputId = id ?? generated;
  const describedBy = error
    ? `${inputId}-error`
    : hint
      ? `${inputId}-hint`
      : undefined;

  return (
    <div className="w-full">
      {label && (
        <label
          htmlFor={inputId}
          className="mb-1.5 block text-[13px] font-medium text-muted"
        >
          {label}
        </label>
      )}

      <div className="relative">
        {leading && (
          <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted">
            {leading}
          </span>
        )}
        <input
          ref={ref}
          id={inputId}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy}
          className={cn(
            control,
            error ? "border-danger" : "border-border hover:border-border-strong",
            leading && "pl-10",
            trailing && "pr-10",
            className,
          )}
          {...rest}
        />
        {trailing && (
          <span className="absolute right-3 top-1/2 -translate-y-1/2 text-muted">
            {trailing}
          </span>
        )}
      </div>

      {/* Reserve nothing: the message appears only when there is one, and
          forms below are laid out with gap rather than fixed heights. */}
      {error ? (
        <p id={`${inputId}-error`} className="mt-1.5 text-[13px] text-danger">
          {error}
        </p>
      ) : hint ? (
        <p id={`${inputId}-hint`} className="mt-1.5 text-[13px] text-muted">
          {hint}
        </p>
      ) : null}
    </div>
  );
});

export type SelectProps = React.SelectHTMLAttributes<HTMLSelectElement> & {
  label?: string;
  hint?: string;
  error?: string | null;
};

export const Select = forwardRef<HTMLSelectElement, SelectProps>(function Select(
  { label, hint, error, className, id, children, ...rest },
  ref,
) {
  const generated = useId();
  const selectId = id ?? generated;

  return (
    <div className="w-full">
      {label && (
        <label
          htmlFor={selectId}
          className="mb-1.5 block text-[13px] font-medium text-muted"
        >
          {label}
        </label>
      )}
      <div className="relative">
        <select
          ref={ref}
          id={selectId}
          aria-invalid={error ? true : undefined}
          className={cn(
            control,
            "appearance-none pr-10",
            error ? "border-danger" : "border-border hover:border-border-strong",
            className,
          )}
          {...rest}
        >
          {children}
        </select>
        <svg
          viewBox="0 0 12 12"
          aria-hidden="true"
          className="pointer-events-none absolute right-3.5 top-1/2 h-3 w-3 -translate-y-1/2 text-muted"
        >
          <path
            d="M2.5 4.5 6 8l3.5-3.5"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </div>
      {error ? (
        <p className="mt-1.5 text-[13px] text-danger">{error}</p>
      ) : hint ? (
        <p className="mt-1.5 text-[13px] text-muted">{hint}</p>
      ) : null}
    </div>
  );
});
