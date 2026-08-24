import { cn } from "@/lib/cn";

type Tone = "neutral" | "accent" | "success" | "danger" | "held" | "outline";

const tones: Record<Tone, string> = {
  neutral: "bg-surface-2 text-muted border-border",
  // Amber, so reserved for something genuinely primary -- a live hold, an
  // active filter. Not for decoration.
  accent: "bg-accent-soft text-accent border-accent/25",
  success: "bg-success-soft text-success border-success/25",
  danger: "bg-danger-soft text-danger border-danger/25",
  held: "text-text border-border",
  outline: "bg-transparent text-muted border-border",
};

export function Badge({
  tone = "neutral",
  className,
  children,
  ...rest
}: React.HTMLAttributes<HTMLSpanElement> & { tone?: Tone }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5",
        "text-[11px] font-medium uppercase tracking-[0.08em]",
        tones[tone],
        // The held tone carries the same hatch as a held seat, so the legend
        // and the seat map are visibly the same language.
        tone === "held" && "hatch-held",
        className,
      )}
      {...rest}
    >
      {children}
    </span>
  );
}
