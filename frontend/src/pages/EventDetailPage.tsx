import { useParams, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import {
  ArrowLeft,
  Loader2,
  Calendar,
  Tag,
  Globe,
  TrendingUp,
  TrendingDown,
  Minus,
} from "lucide-react";
import { getEventDetail } from "@/api/events";
import { ArticleCard } from "@/components/article/ArticleCard";
import { CategoryTag } from "@/components/category/CategoryTag";
import { useReadHistory } from "@/hooks/useReadHistory";

export default function EventDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { t } = useTranslation();
  const { isRead } = useReadHistory();

  const { data: event, isLoading, isError } = useQuery({
    queryKey: ["eventDetail", id],
    queryFn: () => getEventDetail(id!),
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

  if (isError || !event) {
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
    event.sentimentAvg != null && event.sentimentAvg > 0.1 ? (
      <TrendingUp className="h-4 w-4 text-sentiment-positive" />
    ) : event.sentimentAvg != null && event.sentimentAvg < -0.1 ? (
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

      {/* Event header */}
      <div className="mb-6 rounded-lg border border-border bg-card p-6">
        <h1 className="mb-4 text-2xl font-bold text-foreground sm:text-3xl">
          {event.title}
        </h1>

        {/* Metadata grid */}
        <div className="grid gap-3 text-sm sm:grid-cols-2">
          {event.eventType && (
            <div className="flex items-center gap-2 text-muted-foreground">
              <Tag className="h-4 w-4" />
              <span>{event.eventType}</span>
            </div>
          )}
          {event.primaryEntity && (
            <div className="flex items-center gap-2 text-muted-foreground">
              <Globe className="h-4 w-4" />
              <span>
                {event.primaryEntity}
                {event.entityType ? ` (${event.entityType})` : ""}
              </span>
            </div>
          )}
          {event.firstSeenAt && (
            <div className="flex items-center gap-2 text-muted-foreground">
              <Calendar className="h-4 w-4" />
              <span>{new Date(event.firstSeenAt).toLocaleDateString()}</span>
              {event.lastUpdatedAt && (
                <span className="text-xs">
                  - {new Date(event.lastUpdatedAt).toLocaleDateString()}
                </span>
              )}
            </div>
          )}
          {event.sentimentAvg != null && (
            <div className="flex items-center gap-2">
              {sentimentIcon}
              <span className="text-muted-foreground">
                {t("sentiment." + (event.sentimentAvg > 0.1 ? "positive" : event.sentimentAvg < -0.1 ? "negative" : "neutral"))}
                {" "}({event.sentimentAvg.toFixed(2)})
              </span>
            </div>
          )}
        </div>

        {/* Categories */}
        {event.categories && event.categories.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {event.categories.map((cat) => (
              <CategoryTag key={cat} category={cat} size="sm" />
            ))}
          </div>
        )}

        {/* Sources */}
        {event.sources && event.sources.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {event.sources.map((source) => (
              <span
                key={source}
                className="inline-flex items-center rounded-md bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground"
              >
                {source}
              </span>
            ))}
          </div>
        )}

        {/* Representative summary */}
        {event.representativeSummary && (
          <p className="mt-4 text-sm leading-relaxed text-muted-foreground">
            {event.representativeSummary}
          </p>
        )}
      </div>

      {/* Related articles */}
      {event.articles && event.articles.length > 0 && (
        <section>
          <h2 className="mb-3 text-lg font-bold text-foreground">
            {t("events.articles")} ({event.articles.length})
          </h2>
          <div className="flex flex-col gap-3">
            {event.articles.map((article) => (
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
