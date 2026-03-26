import { useTranslation } from "react-i18next";
import type { TimelineEntry } from "@/api/stories";

interface StoryTimelineProps {
  timeline: TimelineEntry[];
}

function formatDate(dateStr: string, locale: string): string {
  const date = new Date(dateStr);
  if (isNaN(date.getTime())) return dateStr;
  return date.toLocaleDateString(locale === "zh" ? "zh-CN" : "en-US");
}

export function StoryTimeline({ timeline }: StoryTimelineProps) {
  const { i18n } = useTranslation();

  if (timeline.length === 0) return null;

  return (
    <div className="relative ml-4 border-l-2 border-primary/20 pl-6 space-y-6">
      {timeline.map((entry, idx) => (
        <div key={idx} className="relative">
          <div className="absolute -left-[31px] top-1 h-3 w-3 rounded-full border-2 border-primary bg-background" />
          <time className="text-xs font-medium text-muted-foreground">
            {formatDate(entry.date, i18n.language)}
          </time>
          <p className="mt-1 text-sm text-foreground leading-relaxed">
            {entry.summary}
          </p>
        </div>
      ))}
    </div>
  );
}
