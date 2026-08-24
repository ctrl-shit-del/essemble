"use client";

import { useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider } from "@/components/auth/AuthProvider";
import { ToastProvider } from "@/components/ui/Toast";
import { WakingBanner } from "@/components/WakingBanner";
import { isApiError } from "@/lib/api";

/**
 * Query defaults are tuned for a booking engine rather than a content site.
 *
 * The important one is the retry rule. A 409 SEAT_UNAVAILABLE means someone
 * else took the seat; retrying is not just pointless, it is a second attempt
 * at a seat that is legitimately gone. Same for an expired hold or a claimed
 * offer. Only genuine transport failures are worth another go -- and those
 * get more attempts than usual, because the free-tier instance can drop the
 * first request of the day while it starts.
 */
function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        gcTime: 5 * 60_000,
        refetchOnWindowFocus: false,
        retry: (failureCount, error) => {
          if (isApiError(error)) {
            if (error.code === "NETWORK_ERROR" || error.code === "TIMEOUT") {
              return failureCount < 2;
            }
            return false;
          }
          return failureCount < 1;
        },
        retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 8000),
      },
      mutations: {
        // Never automatic. A retried POST /holds is a second hold attempt,
        // and the caller decides whether that is what it wants.
        retry: false,
      },
    },
  });
}

export function Providers({ children }: { children: React.ReactNode }) {
  // In state, not module scope: a module-level client would be shared across
  // requests during SSR and leak one user's data into another's render.
  const [queryClient] = useState(makeQueryClient);

  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <AuthProvider>
          <WakingBanner />
          {children}
        </AuthProvider>
      </ToastProvider>
    </QueryClientProvider>
  );
}
