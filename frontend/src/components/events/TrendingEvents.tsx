import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Flame, Newspaper, TrendingUp, TrendingDown, Minus } from "lucide-react";
import { getTrendingEvents } from "@/api/events";
import type { NewsEvent } from "@/api/events";
import { CategoryTag } from "@/components/category/CategoryTag";
import { TrendingEventsSkeleton } from "./EventItemSkeleton";

function SentimentIndicator({ value }: { value: number | null }) {
  if (value == null) return null;

  if (value > 0.1) {
    return (
      <span className="inline-flex items-center gap-0.5 text-xs text-sentiment-positive">
        <TrendingUp className="h-3 w-3" />
        {value.toFixed(1)}
      </span>
    );
  }
  if (value < -0.1) {
    return (
      <span className="inline-flex items-center gap-0.5 text-xs text-sentiment-negative">
        <TrendingDown className="h-3 w-3" />
        {value.toFixed(1)}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-0.5 text-xs text-sentiment-neutral">
      <Minus className="h-3 w-3" />
      {value.toFixed(1)}
    </span>
  );
}

function EventItem({ event }: { event: NewsEvent }) {
  const navigate = useNavigate();
  const { t } = useTranslation();

  return (
    <div
      onClick={() => navigate(`/events/${event.id}`)}
      className="cursor-pointer rounded-lg border border-border bg-card p-3 transition-all hover:shadow-md hover:border-primary/30"
    >
      <div className="flex items-start gap-2">
        <Flame className="mt-0.5 h-4 w-4 flex-shrink-0 text-orange-500 dark:text-orange-400" />
        <div className="min-w-0 flex-1">
          <h4 className="line-clamp-1 text-sm font-semibold text-foreground">
            {event.title}
          </h4>
          <div className="mt-1 flex items-center gap-2 flex-wrap">
            <span className="text-xs text-muted-foreground">
              {event.articleCount} {t("events.sources")}
            </span>
            {event.categories?.slice(0, 2).map((cat) => (
              <CategoryTag key={cat} category={cat} size="sm" />
            ))}
            <SentimentIndicator value={event.sentimentAvg} />
          </div>
        </div>
      </div>
    </div>
  );
}

export function TrendingEvents() {
  const { t } = useTranslation();

  const { data: events, isLoading } = useQuery({
    queryKey: ["trendingEvents"],
    queryFn: () => getTrendingEvents(),
    staleTime: 2 * 60 * 1000,
  });

  if (isLoading) {
    return <TrendingEventsSkeleton />;
  }

  if (!events || events.length === 0) {
    return null;
  }

  return (
    <section>
      <div className="mb-3 flex items-center gap-2">
        <Newspaper className="h-5 w-5 text-primary" />
        <h2 className="text-lg font-bold text-foreground">
          {t("events.trending")}
        </h2>
      </div>
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {events.map((event) => (
          <EventItem key={event.id} event={event} />
        ))}
      </div>
    </section>
  );
}
