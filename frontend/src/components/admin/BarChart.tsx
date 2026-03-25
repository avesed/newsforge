interface BarChartItem {
  label: string;
  value: number;
  color?: string;
}

interface BarChartProps {
  data: BarChartItem[];
  maxValue?: number;
  className?: string;
}

export function BarChart({ data, maxValue, className }: BarChartProps) {
  const max = maxValue ?? Math.max(...data.map((d) => d.value), 1);

  return (
    <div className={`flex flex-col gap-2 ${className ?? ""}`}>
      {data.map((item) => {
        const pct = Math.round((item.value / max) * 100);
        return (
          <div key={item.label} className="flex items-center gap-3">
            <span className="w-24 shrink-0 truncate text-sm text-muted-foreground">
              {item.label}
            </span>
            <div className="relative h-5 flex-1 overflow-hidden rounded-full bg-muted">
              <div
                className="absolute inset-y-0 left-0 rounded-full transition-all duration-500"
                style={{
                  width: `${pct}%`,
                  backgroundColor: item.color ?? "hsl(var(--primary))",
                  minWidth: item.value > 0 ? "4px" : "0px",
                }}
              />
            </div>
            <span className="w-12 shrink-0 text-right text-sm font-medium text-foreground">
              {item.value}
            </span>
          </div>
        );
      })}
    </div>
  );
}
