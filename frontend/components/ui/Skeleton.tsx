import { cn } from "@/lib/cn";

/**
 * Loading placeholder.
 *
 * A sweep rather than a pulse: a pulsing block on a dark background reads as
 * something blinking for attention, while a sweep reads as work in progress.
 */
export function Skeleton({
  className,
  ...rest
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      aria-hidden="true"
      className={cn(
        "relative overflow-hidden rounded-md bg-surface-2",
        "after:absolute after:inset-0 after:-translate-x-full",
        "after:bg-gradient-to-r after:from-transparent after:via-white/[0.04] after:to-transparent",
        "after:animate-[essemble-shimmer_1.6s_infinite]",
        className,
      )}
      {...rest}
    />
  );
}

export function SkeletonText({
  lines = 3,
  className,
}: {
  lines?: number;
  className?: string;
}) {
  return (
    <div className={cn("space-y-2", className)}>
      {Array.from({ length: lines }).map((_, index) => (
        <Skeleton
          key={index}
          className={cn("h-3.5", index === lines - 1 ? "w-2/3" : "w-full")}
        />
      ))}
    </div>
  );
}
