import * as ToastPrimitive from "@radix-ui/react-toast";
import { X } from "lucide-react";
import { useToastStore, type ToastVariant } from "@/stores/toastStore";
import { cn } from "@/lib/utils";

const variantStyles: Record<ToastVariant, string> = {
  default: "border-border bg-card text-foreground",
  success:
    "border-green-500/30 bg-green-50 text-green-800 dark:bg-green-950/50 dark:text-green-200",
  error:
    "border-red-500/30 bg-red-50 text-red-800 dark:bg-red-950/50 dark:text-red-200",
  warning:
    "border-amber-500/30 bg-amber-50 text-amber-800 dark:bg-amber-950/50 dark:text-amber-200",
};

export function Toaster() {
  const toasts = useToastStore((s) => s.toasts);
  const dismissToast = useToastStore((s) => s.dismissToast);

  return (
    <ToastPrimitive.Provider swipeDirection="right" duration={4000}>
      {toasts.map((toast) => (
        <ToastPrimitive.Root
          key={toast.id}
          duration={toast.duration ?? 4000}
          onOpenChange={(open) => {
            if (!open) dismissToast(toast.id);
          }}
          className={cn(
            "pointer-events-auto flex w-[320px] items-start gap-3 rounded-lg border p-4 shadow-lg",
            "data-[state=open]:animate-toast-in data-[state=closed]:animate-toast-out",
            variantStyles[toast.variant],
          )}
        >
          <div className="flex-1 space-y-1">
            <ToastPrimitive.Title className="text-sm font-semibold leading-tight">
              {toast.title}
            </ToastPrimitive.Title>
            {toast.description && (
              <ToastPrimitive.Description className="text-xs opacity-80">
                {toast.description}
              </ToastPrimitive.Description>
            )}
          </div>
          <ToastPrimitive.Close
            aria-label="Close"
            className="shrink-0 rounded p-0.5 opacity-60 transition-opacity hover:opacity-100"
          >
            <X className="h-4 w-4" />
          </ToastPrimitive.Close>
        </ToastPrimitive.Root>
      ))}

      <ToastPrimitive.Viewport className="fixed bottom-20 right-4 z-[100] flex flex-col gap-2 lg:bottom-6" />
    </ToastPrimitive.Provider>
  );
}
