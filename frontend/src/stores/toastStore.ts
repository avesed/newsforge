import { create } from "zustand";

type ToastVariant = "default" | "success" | "error" | "warning";

interface ToastItem {
  id: string;
  title: string;
  description?: string;
  variant: ToastVariant;
  duration?: number;
}

interface ToastState {
  toasts: ToastItem[];
}

interface ToastActions {
  addToast: (toast: Omit<ToastItem, "id">) => void;
  dismissToast: (id: string) => void;
}

const MAX_TOASTS = 5;

function generateId(): string {
  try {
    return crypto.randomUUID();
  } catch {
    // Fallback for non-secure contexts (HTTP on LAN)
    return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
  }
}

export const useToastStore = create<ToastState & ToastActions>((set) => ({
  toasts: [],

  addToast: (toast) => {
    const id = generateId();
    const duration = toast.duration ?? 4000;

    set((state) => ({
      toasts: [...state.toasts, { ...toast, id }].slice(-MAX_TOASTS),
    }));

    // Safety net: auto-dismiss after duration + buffer, in case Radix callback fails
    setTimeout(() => {
      set((state) => ({
        toasts: state.toasts.filter((t) => t.id !== id),
      }));
    }, duration + 500);
  },

  dismissToast: (id) =>
    set((state) => ({
      toasts: state.toasts.filter((t) => t.id !== id),
    })),
}));

/** Standalone toast function for use outside React components. */
export function toast(opts: Omit<ToastItem, "id">): void {
  useToastStore.getState().addToast(opts);
}

export type { ToastVariant, ToastItem };
