import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { Newspaper } from "lucide-react";
import type { TimelineEntry } from "@/api/stories";

interface StoryTimelineProps {
  timeline: TimelineEntry[];
}

function formatDate(dateStr: string, locale: string): string {
  const date = new Date(dateStr);
  if (isNaN(date.getTime())) return dateStr;
  return date.toLocaleDateString(locale === "zh" ? "zh-CN" : "en-US");
}

function entrySortKey(entry: TimelineEntry): number {
  const t = new Date(entry.date).getTime();
  return Number.isNaN(t) ? 0 : t;
}

export function StoryTimeline({ timeline }: StoryTimelineProps) {
  const { i18n } = useTranslation();

  const sorted = useMemo(
    () => [...timeline].sort((a, b) => entrySortKey(a) - entrySortKey(b)),
    [timeline],
  );

  if (sorted.length === 0) return null;

  return (
    <div className="relative ml-4 border-l-2 border-primary/20 pl-6 space-y-6">
      {sorted.map((entry, idx) => {
        const articleId = entry.articleId ?? entry.article_id ?? null;
        const isArticle = entry.kind === "article" || (!entry.summary && !!entry.title);
        const body = entry.summary || entry.title || "";
        return (
          <div key={idx} className="relative">
            <div
              className={`absolute -left-[31px] top-1 h-3 w-3 rounded-full border-2 ${
                isArticle
                  ? "border-muted-foreground/40 bg-background"
                  : "border-primary bg-background"
              }`}
            />
            <div className="flex items-center gap-1.5">
              <time className="text-xs font-medium text-muted-foreground">
                {formatDate(entry.date, i18n.language)}
              </time>
              {isArticle && (
                <Newspaper className="h-3 w-3 text-muted-foreground/70" />
              )}
            </div>
            {articleId ? (
              <Link
                to={`/article/${articleId}`}
                className="mt-1 block text-sm leading-relaxed text-foreground hover:text-primary hover:underline"
              >
                {body}
              </Link>
            ) : (
              <p className="mt-1 text-sm leading-relaxed text-foreground">
                {body}
              </p>
            )}
          </div>
        );
      })}
    </div>
  );
}
