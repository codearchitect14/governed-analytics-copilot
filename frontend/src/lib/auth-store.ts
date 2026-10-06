import { create } from "zustand";

export interface SessionUser {
  id: string;
  email: string;
  full_name: string;
  role: string;
  policy_version: number;
}

interface AuthState {
  /** Starts as "loading" until the first silent refresh finishes. */
  status: "loading" | "authenticated" | "anonymous";
  user: SessionUser | null;
  /** Kept in memory only. Never written to localStorage or sessionStorage. */
  accessToken: string | null;
  accessExpiresAt: number | null;
  setSession: (user: SessionUser, accessToken: string, expiresAt: string) => void;
  clear: () => void;
}

export const useAuth = create<AuthState>((set) => ({
  status: "loading",
  user: null,
  accessToken: null,
  accessExpiresAt: null,
  setSession: (user, accessToken, expiresAt) =>
    set({
      status: "authenticated",
      user,
      accessToken,
      accessExpiresAt: Date.parse(expiresAt),
    }),
  clear: () => set({ status: "anonymous", user: null, accessToken: null, accessExpiresAt: null }),
}));

export function isAdmin(user: SessionUser | null): boolean {
  return user?.role === "admin";
}
