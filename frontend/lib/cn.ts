/**
 * Class name joiner.
 *
 * Deliberately not clsx + tailwind-merge: nothing here relies on later
 * classes overriding earlier ones, and two dependencies to concatenate
 * strings is not a trade this project needs to make.
 *
 * Accepts anything and keeps only non-empty strings. That matters for the
 * common `someNode && "a-class"` guard: when the guard is a ReactNode the
 * expression can evaluate to 0 or "" rather than false, which a narrower
 * signature would reject at compile time for no useful reason.
 */
export function cn(...parts: unknown[]): string {
  let out = "";
  for (const part of parts) {
    if (typeof part === "string" && part.length > 0) {
      out = out ? `${out} ${part}` : part;
    }
  }
  return out;
}
