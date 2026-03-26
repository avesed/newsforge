import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";

interface StatusBadgeProps {
  status: string;
}

const STATUS_CONFIG: Record<string, { dot: string; text: string }> = {
  developing: { dot: "bg-blue-500 animate-pulse", text: "text-blue-500" },
  ongoing: { dot: "bg-green-500", text: "text-green-500" },
  concluded: { dot: "bg-gray-400", text: "text-gray-400" },
};

const DEFAULT_CONFIG = { dot: "bg-gray-400", text: "text-gray-400" };

export function StatusBadge({ status }: StatusBadgeProps) {
  const { t } = useTranslation();

  const config = STATUS_CONFIG[status] ?? DEFAULT_CONFIG;

  return (
    <span className={cn("inline-flex items-center gap-1.5 text-xs font-medium", config.text)}>
      <span className={cn("h-1.5 w-1.5 rounded-full", config.dot)} />
      {t(`stories.status.${status}`, status)}
    </span>
  );
}
