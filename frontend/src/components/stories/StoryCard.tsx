import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { BookOpen, TrendingUp, TrendingDown, Minus } from "lucide-react";
import type { NewsStory } from "@/api/stories";
import { CategoryTag } from "@/components/category/CategoryTag";
import { StatusBadge } from "./StatusBadge";

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

interface StoryCardProps {
  story: NewsStory;
}

export function StoryCard({ story }: StoryCardProps) {
  const { t } = useTranslation();

  return (
    <Link
      to={`/stories/${story.id}`}
      aria-label={story.title}
      className="block touch-press cursor-pointer rounded-lg border border-border bg-card p-3 transition-all hover:shadow-md hover:border-primary/30 focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none"
    >
      <div className="flex items-start gap-2">
        <BookOpen className="mt-0.5 h-4 w-4 flex-shrink-0 text-primary" />
        <div className="min-w-0 flex-1">
          <h4 className="line-clamp-1 text-sm font-semibold text-foreground">
            {story.title}
          </h4>
          <div className="mt-1 flex items-center gap-2 flex-wrap">
            <StatusBadge status={story.status} />
            <span className="text-xs text-muted-foreground">
              {story.articleCount} {t("stories.articles")}
            </span>
            {story.categories?.slice(0, 2).map((cat) => (
              <CategoryTag key={cat} category={cat} size="sm" />
            ))}
            <SentimentIndicator value={story.sentimentAvg} />
          </div>
          {story.keyEntities && story.keyEntities.length > 0 && (
            <div className="mt-1.5 flex items-center gap-1.5 flex-wrap">
              {story.keyEntities.slice(0, 2).map((entity) => (
                <span
                  key={entity}
                  className="inline-flex items-center rounded px-1.5 py-0.5 text-xs text-muted-foreground bg-muted"
                >
                  {entity}
                </span>
              ))}
            </div>
          )}
        </div>
      </div>
    </Link>
  );
}
