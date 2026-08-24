"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import {
  clearSession,
  getSnapshot,
  listenForCrossTabChanges,
  restoreSession,
  setSession,
  subscribe,
  type AuthSnapshot,
} from "@/lib/auth-store";
import { tokenResponseSchema, userSchema, type User, type UserRole } from "@/lib/types";

/** Where each role lands after signing in. */
export const HOME_FOR_ROLE: Record<UserRole, string> = {
  customer: "/",
  organiser: "/organiser",
  admin: "/admin",
};

type AuthContextValue = {
  user: User | null;
  token: string | null;
  /** True until localStorage has been read. Guards must wait for this. */
  loading: boolean;
  login: (email: string, password: string) => Promise<User>;
  register: (input: RegisterInput) => Promise<User>;
  logout: () => void;
  refreshUser: () => Promise<void>;
};

export type RegisterInput = {
  email: string;
  password: string;
  name: string;
  /** Admin accounts are seeded, never self-registered; the API refuses it. */
  role: Exclude<UserRole, "admin">;
  phone?: string;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside <AuthProvider>");
  return context;
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [snapshot, setSnapshot] = useState<AuthSnapshot>(getSnapshot);
  const [loading, setLoading] = useState(true);
  const router = useRouter();
  const queryClient = useQueryClient();

  // Rehydrate after mount, never during render: reading localStorage while
  // rendering makes the server and client markup disagree.
  useEffect(() => {
    setSnapshot(restoreSession());
    setLoading(false);
    const unsubscribeStore = subscribe(setSnapshot);
    const unsubscribeTabs = listenForCrossTabChanges();
    return () => {
      unsubscribeStore();
      unsubscribeTabs();
    };
  }, []);

  const login = useCallback(
    async (email: string, password: string) => {
      const result = await api.post("/api/auth/login", tokenResponseSchema, {
        email,
        password,
      });
      setSession(result.access_token, result.user);
      // The previous user's cached data must not survive a switch.
      queryClient.clear();
      return result.user;
    },
    [queryClient],
  );

  const register = useCallback(
    async (input: RegisterInput) => {
      const result = await api.post("/api/auth/register", tokenResponseSchema, input);
      setSession(result.access_token, result.user);
      queryClient.clear();
      return result.user;
    },
    [queryClient],
  );

  const logout = useCallback(() => {
    clearSession();
    queryClient.clear();
    router.push("/login");
  }, [queryClient, router]);

  /** Re-read the account, e.g. after a role or profile change. */
  const refreshUser = useCallback(async () => {
    const current = getSnapshot();
    if (!current.token) return;
    const user = await api.get("/api/auth/me", userSchema);
    setSession(current.token, user);
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      user: snapshot.user,
      token: snapshot.token,
      loading,
      login,
      register,
      logout,
      refreshUser,
    }),
    [snapshot, loading, login, register, logout, refreshUser],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
