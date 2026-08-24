import Link from "next/link";
import { cn } from "@/lib/cn";

/**
 * The wordmark. One mark, three lockups.
 *
 * The suffix is what tells an operator which product surface they are in, so
 * it is set in the UI sans at small caps against the display serif of the
 * name -- the contrast does the work, not a colour change.
 */
export function Brand({
  suffix,
  href = "/",
  className,
  compact = false,
}: {
  suffix?: "ORGANISER" | "ADMIN";
  href?: string;
  className?: string;
  compact?: boolean;
}) {
  return (
    <Link
      href={href}
      className={cn(
        "group inline-flex items-baseline gap-2 rounded-md",
        "transition-opacity duration-150 hover:opacity-90",
        className,
      )}
      aria-label={suffix ? `ESSEMBLE ${suffix}` : "ESSEMBLE"}
    >
      <span
        className={cn(
          "font-display font-semibold leading-none tracking-[-0.02em] text-text",
          compact ? "text-[17px]" : "text-[19px]",
        )}
      >
        ESSEMBLE
      </span>

      {suffix && (
        <>
          <span aria-hidden="true" className="text-border-strong">
            /
          </span>
          <span className="text-[10px] font-semibold uppercase tracking-[0.18em] text-accent">
            {suffix}
          </span>
        </>
      )}
    </Link>
  );
}
