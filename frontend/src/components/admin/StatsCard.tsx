import { type LucideIcon } from "lucide-react";

interface StatsCardProps {
  label: string;
  value: string | number;
  subtitle?: string;
  icon?: LucideIcon;
  trend?: { value: number; label: string };
  className?: string;
}

export function StatsCard({ label, value, subtitle, icon: Icon, trend, className }: StatsCardProps) {
  return (
    <div
      className={`rounded-lg border border-border bg-card p-5 ${className ?? ""}`}
    >
      <div className="flex items-center justify-between">
        <p className="text-sm font-medium text-muted-foreground">{label}</p>
        {Icon && <Icon className="h-4 w-4 text-muted-foreground" />}
      </div>
      <p className="mt-2 text-3xl font-bold text-foreground">{value}</p>
      {subtitle && (
        <p className="mt-0.5 text-xs text-muted-foreground">{subtitle}</p>
      )}
      {trend && (
        <p
          className={`mt-1 text-xs font-medium ${
            trend.value >= 0
              ? "text-green-600 dark:text-green-400"
              : "text-red-600 dark:text-red-400"
          }`}
        >
          {trend.value >= 0 ? "+" : ""}
          {trend.value} {trend.label}
        </p>
      )}
    </div>
  );
}
