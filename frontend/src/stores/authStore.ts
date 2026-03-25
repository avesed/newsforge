import { create } from "zustand";
import type { User } from "@/types";
import * as authApi from "@/api/auth";

interface AuthState {
  user: User | null;
  token: string | null;
  isLoading: boolean;
}

interface AuthActions {
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, displayName: string) => Promise<void>;
  logout: () => Promise<void>;
  initAuth: () => Promise<void>;
  isAdmin: () => boolean;
  isAuthenticated: () => boolean;
}

export const useAuthStore = create<AuthState & AuthActions>((set, get) => ({
  user: null,
  token: localStorage.getItem("access_token"),
  isLoading: true,

  login: async (email, password) => {
    const response = await authApi.login({ email, password });
    localStorage.setItem("access_token", response.accessToken);
    set({ token: response.accessToken });
    const user = await authApi.getMe();
    set({ user });
  },

  register: async (email, password, displayName) => {
    const response = await authApi.register({ email, password, displayName });
    localStorage.setItem("access_token", response.accessToken);
    set({ token: response.accessToken });
    const user = await authApi.getMe();
    set({ user });
  },

  logout: async () => {
    try {
      await authApi.logout();
    } catch {
      // Ignore logout errors
    }
    localStorage.removeItem("access_token");
    set({ user: null, token: null });
  },

  initAuth: async () => {
    const token = localStorage.getItem("access_token");
    if (!token) {
      set({ isLoading: false });
      return;
    }
    try {
      const user = await authApi.getMe();
      set({ user, token, isLoading: false });
    } catch {
      localStorage.removeItem("access_token");
      set({ user: null, token: null, isLoading: false });
    }
  },

  isAdmin: () => get().user?.role === "admin",
  isAuthenticated: () => get().user !== null,
}));
