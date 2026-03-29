import { useParams, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import {
  ArrowLeft,
  Loader2,
  Calendar,
  Newspaper,
  Clock,
  TrendingUp,
  TrendingDown,
  Minus,
} from "lucide-react";
import { getStoryDetail } from "@/api/stories";
import { ArticleCard } from "@/components/article/ArticleCard";
import { CategoryTag } from "@/components/category/CategoryTag";
import { StatusBadge } from "@/components/stories/StatusBadge";
import { StoryTimeline } from "@/components/stories/StoryTimeline";
import { useReadHistory } from "@/hooks/useReadHistory";
import { useSwipeBack } from "@/hooks/useSwipeBack";

export default function StoryDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { t, i18n } = useTranslation();
  const locale = i18n.language === "zh" ? "zh-CN" : "en-US";
  const { isRead } = useReadHistory();
  useSwipeBack();

  const { data: story, isLoading, isError } = useQuery({
    queryKey: ["storyDetail", id],
    queryFn: () => getStoryDetail(id ?? ""),
    enabled: !!id,
    staleTime: 5 * 60 * 1000,
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (isError || !story) {
    return (
      <div className="flex flex-col items-center justify-center py-12">
        <p className="text-muted-foreground">{t("common.error")}</p>
        <button
          onClick={() => navigate(-1)}
          className="mt-2 rounded-md bg-primary px-4 py-2 text-sm text-primary-foreground"
        >
          {t("common.back")}
        </button>
      </div>
    );
  }

  const sentimentIcon =
    story.sentimentAvg != null && story.sentimentAvg > 0.1 ? (
      <TrendingUp className="h-4 w-4 text-sentiment-positive" />
    ) : story.sentimentAvg != null && story.sentimentAvg < -0.1 ? (
      <TrendingDown className="h-4 w-4 text-sentiment-negative" />
    ) : (
      <Minus className="h-4 w-4 text-sentiment-neutral" />
    );

  return (
    <div className="mx-auto max-w-4xl">
      {/* Back button */}
      <button
        onClick={() => navigate(-1)}
        className="mb-4 flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" />
        {t("common.back")}
      </button>

      {/* Hero card */}
      <div className="mb-6 rounded-lg border border-border bg-card p-6">
        <h1 className="mb-4 text-2xl font-bold text-foreground sm:text-3xl">
          {story.title}
        </h1>

        {/* Status + story type */}
        <div className="mb-3 flex items-center gap-2">
          <StatusBadge status={story.status} />
          {story.storyType && (
            <span className="rounded bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground">
              {story.storyType}
            </span>
          )}
        </div>

        {/* Description */}
        {story.description && (
          <p className="mb-4 text-sm leading-relaxed text-muted-foreground">
            {story.description}
          </p>
        )}

        {/* Metadata grid */}
        <div className="grid gap-3 text-sm sm:grid-cols-2">
          {story.firstSeenAt && (
            <div className="flex items-center gap-2 text-muted-foreground">
              <Calendar className="h-4 w-4" />
              <span>{new Date(story.firstSeenAt).toLocaleDateString(locale)}</span>
              {story.lastUpdatedAt && (
                <span className="text-xs">
                  - {new Date(story.lastUpdatedAt).toLocaleDateString(locale)}
                </span>
              )}
            </div>
          )}
          <div className="flex items-center gap-2 text-muted-foreground">
            <Newspaper className="h-4 w-4" />
            <span>
              {story.articleCount} {t("stories.sources")}
            </span>
          </div>
          {story.sentimentAvg != null && (
            <div className="flex items-center gap-2">
              {sentimentIcon}
              <span className="text-muted-foreground">
                {t("sentiment." + (story.sentimentAvg > 0.1 ? "positive" : story.sentimentAvg < -0.1 ? "negative" : "neutral"))}
                {" "}({story.sentimentAvg.toFixed(2)})
              </span>
            </div>
          )}
        </div>

        {/* Key entities */}
        {story.keyEntities && story.keyEntities.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {story.keyEntities.map((entity) => (
              <span
                key={entity}
                className="rounded-md bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground"
              >
                {entity}
              </span>
            ))}
          </div>
        )}

        {/* Categories */}
        {story.categories && story.categories.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {story.categories.map((cat) => (
              <CategoryTag key={cat} category={cat} size="sm" />
            ))}
          </div>
        )}
      </div>

      {/* Timeline section */}
      {story.timeline && story.timeline.length > 0 && (
        <section className="mb-6">
          <div className="mb-3 flex items-center gap-2">
            <Clock className="h-5 w-5 text-primary" />
            <h2 className="text-lg font-bold text-foreground">
              {t("stories.timeline")}
            </h2>
          </div>
          <StoryTimeline timeline={story.timeline} />
        </section>
      )}

      {/* Related articles */}
      {story.articles && story.articles.length > 0 && (
        <section>
          <h2 className="mb-3 text-lg font-bold text-foreground">
            {t("stories.articles")} ({story.articles.length})
          </h2>
          <div className="flex flex-col gap-3">
            {story.articles.map((article) => (
              <ArticleCard
                key={article.id}
                article={article}
                isRead={isRead(article.id)}
              />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
