import { cn } from "@/lib/cn";

/**
 * Solid surface, never glass.
 *
 * Glass is reserved for chrome that floats over content -- navbar, modals,
 * the sticky booking bar. A grid of blurred cards over a scrolling page reads
 * as noise and costs a compositor layer each, so cards are opaque by rule.
 */
export function Card({
  className,
  interactive = false,
  elevated = false,
  ...rest
}: React.HTMLAttributes<HTMLDivElement> & {
  /** Adds hover affordance. Use only when the whole card is clickable. */
  interactive?: boolean;
  elevated?: boolean;
}) {
  return (
    <div
      className={cn(
        "rounded-xl border border-border",
        elevated ? "bg-surface-2" : "bg-surface",
        interactive &&
          "transition-[border-color,transform,background-color] duration-200 " +
            "hover:-translate-y-0.5 hover:border-border-strong hover:bg-surface-2 " +
            "focus-within:border-border-strong",
        className,
      )}
      {...rest}
    />
  );
}

export function CardHeader({
  className,
  ...rest
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("flex items-start justify-between gap-4 p-5 pb-0", className)}
      {...rest}
    />
  );
}

export function CardTitle({
  className,
  ...rest
}: React.HTMLAttributes<HTMLHeadingElement>) {
  return (
    <h3
      className={cn("font-display text-lg leading-tight text-text", className)}
      {...rest}
    />
  );
}

export function CardBody({
  className,
  ...rest
}: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("p-5", className)} {...rest} />;
}

export function CardFooter({
  className,
  ...rest
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "flex items-center justify-between gap-3 border-t border-border px-5 py-4",
        className,
      )}
      {...rest}
    />
  );
}
