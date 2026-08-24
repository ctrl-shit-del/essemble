"use client";

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import { HOME_FOR_ROLE, useAuth } from "./AuthProvider";
import type { UserRole } from "@/lib/types";
import { Skeleton } from "@/components/ui/Skeleton";

/**
 * Client-side route protection.
 *
 * Honest about what this is: a routing convenience, not a security boundary.
 * The token lives in the browser, so anyone can render any shell by editing
 * their own JavaScript. Every one of these routes is also enforced server
 * side -- the API re-derives ownership from the database on each request and
 * answers 403 regardless of what the client believes. This exists so a
 * customer does not land on an organiser page full of failed requests.
 */
export function RequireRole({
  allow,
  children,
}: {
  allow: UserRole[];
  children: React.ReactNode;
}) {
  const { user, loading } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  const allowed = user ? allow.includes(user.role) : false;

  useEffect(() => {
    if (loading) return;

    if (!user) {
      // Carry the destination so login can return them to it.
      const next = encodeURIComponent(pathname ?? "/");
      router.replace(`/login?next=${next}`);
      return;
    }

    if (!allowed) {
      // Signed in, wrong role: send them to their own home rather than to
      // login, which would look like the session had failed.
      router.replace(HOME_FOR_ROLE[user.role]);
    }
  }, [loading, user, allowed, router, pathname]);

  if (loading || !user || !allowed) return <RouteFallback />;

  return <>{children}</>;
}

function RouteFallback() {
  return (
    <div className="mx-auto w-full max-w-5xl px-6 py-16">
      <Skeleton className="h-8 w-52" />
      <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {Array.from({ length: 6 }).map((_, index) => (
          <Skeleton key={index} className="h-40 w-full rounded-xl" />
        ))}
      </div>
    </div>
  );
}

/** For pages that only require a session, whatever the role. */
export function RequireAuth({ children }: { children: React.ReactNode }) {
  return (
    <RequireRole allow={["customer", "organiser", "admin"]}>{children}</RequireRole>
  );
}
