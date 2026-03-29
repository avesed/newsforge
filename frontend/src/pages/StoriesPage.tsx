import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { BookOpen, Clock, TrendingUp } from "lucide-react";
import { listStories } from "@/api/stories";
import { StoryCard } from "@/components/stories/StoryCard";
import { Skeleton } from "@/components/ui/Skeleton";
import { cn } from "@/lib/utils";

function StoriesPageSkeleton() {
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="rounded-lg border border-border bg-card p-3">
          <div className="flex items-start gap-2">
            <Skeleton className="mt-0.5 h-4 w-4 flex-shrink-0 rounded" />
            <div className="min-w-0 flex-1">
              <Skeleton className="h-4 w-full" />
              <div className="mt-1.5 flex items-center gap-2">
                <Skeleton className="h-3 w-16" />
                <Skeleton className="h-3 w-12" />
              </div>
              <div className="mt-1.5 flex items-center gap-2">
                <Skeleton className="h-4 w-10 rounded-full" />
                <Skeleton className="h-4 w-10 rounded-full" />
              </div>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

export default function StoriesPage() {
  const { t } = useTranslation();
  const [sort, setSort] = useState<"recent" | "popular">("recent");

  const {
    data: stories,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ["stories", sort],
    queryFn: () => listStories(undefined, sort),
    staleTime: 2 * 60 * 1000,
  });

  return (
    <div className="animate-page-enter">
      {/* Page header + sort toggle */}
      <div className="mb-6 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <BookOpen className="h-6 w-6 text-primary" />
          <h1 className="text-xl font-bold text-foreground">
            {t("stories.allStories")}
          </h1>
        </div>

        {/* Sort toggle */}
        <div className="flex rounded-full border border-border bg-muted/50 p-0.5">
          <button
            onClick={() => setSort("recent")}
            className={cn(
              "flex items-center gap-1 rounded-full px-3 py-1 text-xs font-medium transition-colors",
              sort === "recent"
                ? "bg-primary text-primary-foreground shadow-sm"
                : "text-muted-foreground"
            )}
          >
            <Clock className="h-3 w-3" />
            {t("stories.sortRecent")}
          </button>
          <button
            onClick={() => setSort("popular")}
            className={cn(
              "flex items-center gap-1 rounded-full px-3 py-1 text-xs font-medium transition-colors",
              sort === "popular"
                ? "bg-primary text-primary-foreground shadow-sm"
                : "text-muted-foreground"
            )}
          >
            <TrendingUp className="h-3 w-3" />
            {t("stories.sortPopular")}
          </button>
        </div>
      </div>

      {isLoading && <StoriesPageSkeleton />}

      {isError && (
        <div className="flex flex-col items-center justify-center py-12">
          <p className="text-muted-foreground">{t("common.error")}</p>
        </div>
      )}

      {!isLoading && !isError && stories && stories.length === 0 && (
        <div className="flex flex-col items-center justify-center py-12">
          <BookOpen className="mb-3 h-10 w-10 text-muted-foreground/40" />
          <p className="text-muted-foreground">{t("stories.noStories")}</p>
        </div>
      )}

      {stories && stories.length > 0 && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {stories.map((story) => (
            <StoryCard key={story.id} story={story} />
          ))}
        </div>
      )}
    </div>
  );
}
