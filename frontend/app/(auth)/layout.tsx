import { Brand } from "@/components/shell/Brand";

/**
 * Auth shell. No nav, no shell chrome -- there is exactly one thing to do on
 * these pages and the surrounding furniture would only offer ways to leave.
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
        <div className="mb-8">
          <Brand />
        </div>
        {children}
      </div>
    </div>
  );
}
