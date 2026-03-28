import { Link, useNavigate } from "react-router-dom";
import { BookOpen, Check, CircleCheck, Clock, TrendingUp } from "lucide-react";
import { useTranslation } from "react-i18next";
import { CATEGORY_COLORS, type CategorySlug } from "@/types";
import { cn } from "@/lib/utils";
import { timeAgo } from "@/lib/timeAgo";
import type { Article } from "@/types";

interface ArticleCardProps {
  article: Article;
  isRead?: boolean;
  onMarkRead?: (id: string) => void;
}

export function ArticleCard({ article, isRead, onMarkRead }: ArticleCardProps) {
  const { t, i18n } = useTranslation();
  const locale = i18n.language === "zh" ? "zh" : "en";
  const navigate = useNavigate();

  return (
    <div
      className={cn(
        "group border-b border-border/50 last:border-b-0",
        article.valueScore != null && article.valueScore > 80
          ? "border-l-2 border-l-amber-400 pl-2"
          : isRead && "border-l-2 border-l-muted-foreground/20 pl-2"
      )}
    >
      <Link
        to={`/article/${article.id}`}
        className={cn(
          "block px-1 py-4 hover:bg-accent/30 dark:hover:bg-accent/50 transition-colors rounded-sm -mx-1",
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
            <span className="flex items-center gap-0.5 text-muted-foreground/50">
              <Check className="h-3 w-3" />
              {t("article.read")}
            </span>
          )}
          {!isRead && onMarkRead && (
            <button
              onClick={(e) => {
                e.preventDefault();
                e.stopPropagation();
                onMarkRead(article.id);
              }}
              className="ml-auto opacity-0 group-hover:opacity-100 transition-opacity text-muted-foreground hover:text-foreground"
              title={t("article.markRead")}
            >
              <CircleCheck className="h-3.5 w-3.5" />
            </button>
          )}
        </div>

        {/* Body: text + optional thumbnail */}
        <div className={cn("flex gap-3", article.imageUrl && "flex-row")}>
          <div className="min-w-0 flex-1">
            {/* Title */}
            <h3 className="font-semibold text-[15px] leading-snug line-clamp-2 mb-1 group-hover:text-primary transition-colors">
              {article.title}
            </h3>

            {/* Summary */}
            {article.summary && (
              <p className="text-sm text-muted-foreground line-clamp-2 mb-2">
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
              {article.storyId && (
                <span
                  role="link"
                  tabIndex={0}
                  onClick={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    navigate(`/stories/${article.storyId}`);
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      e.stopPropagation();
                      navigate(`/stories/${article.storyId}`);
                    }
                  }}
                  className="inline-flex items-center gap-1 rounded-full bg-indigo-500/10 px-2 py-0.5 text-[11px] font-medium text-indigo-500 hover:bg-indigo-500/20 transition-colors cursor-pointer"
                >
                  <BookOpen className="h-3 w-3" />
                  {t("stories.badge")}
                </span>
              )}
            </div>
          </div>

          {/* Thumbnail */}
          {article.imageUrl && (
            <img
              src={article.imageUrl}
              alt=""
              className="h-[60px] w-[80px] flex-shrink-0 rounded-md object-cover"
              loading="lazy"
              onError={(e) => {
                (e.target as HTMLImageElement).style.display = "none";
              }}
            />
          )}
        </div>
      </Link>
    </div>
  );
}
