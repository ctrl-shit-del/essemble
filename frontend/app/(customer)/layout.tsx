import { CustomerNav } from "@/components/shell/CustomerNav";

/**
 * Customer shell. Content-first and generous: a centred column with wide
 * gutters, because this surface is mostly artwork and reading, and its job
 * is to make a film look worth watching.
 *
 * Deliberately NOT wrapped in RequireRole -- browsing is public. Individual
 * routes that need a session (bookings, waitlist) guard themselves.
 */
export default function CustomerLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-dvh bg-bg">
      <CustomerNav />
      <main className="mx-auto max-w-7xl px-6 py-10 lg:py-14">{children}</main>
    </div>
  );
}
