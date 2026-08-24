import Link from "next/link";
import { Brand } from "@/components/shell/Brand";

/**
 * Auth shell.
 *
 * No nav, because there is one thing to do on these pages. But "no nav" was
 * being read as "no exit": the wordmark was already a link to "/" and nothing
 * about it said so, which is the same as not being one. So it now carries a
 * visible hover affordance, and there is an explicit way back above it --
 * someone who clicked Sign in to browse should not have to use the browser
 * button to change their mind.
 */
export default function AuthLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="relative min-h-dvh bg-bg">
      {/* A single warm bloom off the top edge. The only decorative use of
          amber in the product, and it is barely visible by design. */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-x-0 top-0 h-[420px] opacity-[0.07]"
        style={{
          background:
            "radial-gradient(60% 100% at 50% 0%, var(--color-accent) 0%, transparent 70%)",
        }}
      />

      <div className="relative mx-auto flex min-h-dvh w-full max-w-md flex-col justify-center px-6 py-12">
        <Link
          href="/"
          className="mb-5 inline-flex w-fit items-center gap-1.5 text-[13px] text-muted transition-colors hover:text-text"
        >
          <svg viewBox="0 0 12 12" className="h-3 w-3" aria-hidden="true">
            <path
              d="M7.5 2.5 4 6l3.5 3.5"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          Back to what&rsquo;s on
        </Link>

        <div className="mb-8">
          <Brand className="underline decoration-transparent underline-offset-[6px] transition-[text-decoration-color] hover:decoration-accent" />
        </div>

        {children}
      </div>
    </div>
  );
}
