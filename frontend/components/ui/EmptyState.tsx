import { cn } from "@/lib/cn";

/**
 * Nothing here yet, or nothing matched.
 *
 * Always says what to do next. An empty state without an action is a dead
 * end, and this app has several places -- no bookings, no waitlist entries,
 * no shows for a filter -- where the next step is genuinely obvious and
 * should therefore be offered.
 */
export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
}: {
  icon?: React.ReactNode;
  title: string;
  description?: string;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center rounded-xl border border-dashed",
        "border-border px-6 py-14 text-center",
        className,
      )}
    >
      {icon && (
        <div className="mb-4 grid h-11 w-11 place-items-center rounded-full border border-border bg-surface text-muted">
          {icon}
        </div>
      )}
      <h3 className="font-display text-lg text-text">{title}</h3>
      {description && (
        <p className="mt-1.5 max-w-sm text-sm leading-relaxed text-muted">
          {description}
        </p>
      )}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}
