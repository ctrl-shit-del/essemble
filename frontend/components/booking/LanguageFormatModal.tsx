"use client";

import { Modal } from "@/components/ui/Modal";
import { formatLabel, type LanguageFormat } from "@/lib/catalog";
import { cn } from "@/lib/cn";

/**
 * Step 2 of the fixed flow: language + format.
 *
 * The options are derived from the showtimes that actually exist, so every
 * choice here leads somewhere. The caller is responsible for the other half
 * of that rule -- when there is exactly ONE combination it must not open this
 * at all, because asking someone to confirm a decision they do not have is a
 * step that only costs them a click.
 */
export function LanguageFormatModal({
  open,
  options,
  onSelect,
  onClose,
  eventTitle,
}: {
  open: boolean;
  options: LanguageFormat[];
  onSelect: (combination: LanguageFormat) => void;
  onClose: () => void;
  eventTitle: string;
}) {
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Choose language and format"
      description={`${eventTitle} is showing in more than one version.`}
      size="md"
    >
      <ul className="grid gap-2 sm:grid-cols-2">
        {options.map((option) => {
          const key = `${option.language}|${option.format ?? ""}`;
          return (
            <li key={key}>
              <button
                type="button"
                onClick={() => onSelect(option)}
                className={cn(
                  "w-full rounded-lg border border-border bg-surface px-4 py-3.5 text-left",
                  "transition-colors duration-150 hover:border-accent hover:bg-surface-2",
                  "focus-visible:border-accent",
                )}
              >
                <span className="block font-display text-base text-text">
                  {option.language}
                </span>
                <span className="mt-0.5 flex items-baseline gap-2">
                  <span className="text-[13px] text-accent">
                    {formatLabel(option.format)}
                  </span>
                  <span className="text-[12px] text-muted">
                    {option.count} {option.count === 1 ? "show" : "shows"}
                  </span>
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </Modal>
  );
}
