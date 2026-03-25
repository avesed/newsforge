import { Link } from "react-router-dom";
import { Clock, TrendingUp } from "lucide-react";
import { useTranslation } from "react-i18next";
import { CATEGORY_COLORS, type CategorySlug } from "@/types";
import { cn } from "@/lib/utils";
import { timeAgo } from "@/lib/timeAgo";
import type { Article } from "@/types";

interface ArticleCardProps {
  article: Article;
  isRead?: boolean;
}

export function ArticleCard({ article, isRead }: ArticleCardProps) {
  const { i18n } = useTranslation();
  const locale = i18n.language === "zh" ? "zh" : "en";

  return (
    <div className="group border-b border-border/50 last:border-b-0">
      <Link
        to={`/article/${article.id}`}
        className={cn(
          "block px-1 py-4 hover:bg-accent/30 transition-colors rounded-sm -mx-1",
          isRead && "opacity-60"
        )}
      >
        {/* Meta row */}
        <div className="flex items-center gap-2 text-xs text-muted-foreground mb-1.5">
          <span className="font-medium">{article.sourceName || "Unknown"}</span>
          <span className="flex items-center gap-1">
            <Clock className="h-3 w-3" />
            {timeAgo(article.publishedAt, locale)}
          </span>
          {article.hasMarketImpact && (
            <span
              className="text-amber-500 dark:text-amber-400 flex items-center gap-0.5"
              title={article.marketImpactHint ?? undefined}
            >
              <TrendingUp className="h-3 w-3" />
            </span>
          )}
          {isRead && (
            <span className="text-muted-foreground/50">
              {locale === "zh" ? "已读" : "read"}
            </span>
          )}
        </div>

        {/* Title */}
        <h3 className="font-semibold text-[15px] leading-snug line-clamp-2 mb-1 group-hover:text-primary transition-colors">
          {article.title}
        </h3>

        {/* Summary */}
        {article.summary && (
          <p className="text-sm text-muted-foreground line-clamp-1 mb-2">
            {article.summary}
          </p>
        )}

        {/* Tags row: categories + sentiment */}
        <div className="flex flex-wrap items-center gap-1.5">
          {article.categories?.map((cat) => {
            const color = CATEGORY_COLORS[cat as CategorySlug] ?? CATEGORY_COLORS.other;
            return (
              <span
                key={cat}
                className="rounded-full px-2 py-0.5 text-[11px] font-medium"
                style={{
                  backgroundColor: `${color}15`,
                  color: color,
                }}
              >
                {cat}
              </span>
            );
          })}
          {article.sentimentLabel && (
            <span
              className={cn(
                "rounded-full px-2 py-0.5 text-[11px] font-medium",
                article.sentimentLabel === "positive" && "bg-green-500/10 text-green-500",
                article.sentimentLabel === "negative" && "bg-red-500/10 text-red-500",
                article.sentimentLabel === "neutral" && "bg-blue-500/10 text-blue-400"
              )}
            >
              {article.sentimentLabel}
            </span>
          )}
        </div>
      </Link>
    </div>
  );
}
