import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { BookOpen } from "lucide-react";
import { getTrendingStories } from "@/api/stories";
import { StoryCard } from "./StoryCard";
import { TrendingStoriesSkeleton } from "./StoryItemSkeleton";

export function TrendingStories() {
  const { t } = useTranslation();

  const { data: stories, isLoading } = useQuery({
    queryKey: ["trendingStories"],
    queryFn: () => getTrendingStories(),
    staleTime: 2 * 60 * 1000,
  });

  if (isLoading) {
    return <TrendingStoriesSkeleton />;
  }

  if (!stories || stories.length === 0) {
    return null;
  }

  return (
    <section>
      <div className="mb-3 flex items-center gap-2">
        <BookOpen className="h-5 w-5 text-primary" />
        <h2 className="text-lg font-bold text-foreground">
          {t("stories.trending")}
        </h2>
      </div>
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {stories.map((story) => (
          <StoryCard key={story.id} story={story} />
        ))}
      </div>
    </section>
  );
}
