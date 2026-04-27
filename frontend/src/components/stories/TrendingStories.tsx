import { useRef, useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { BookOpen } from "lucide-react";
import { getTrendingStories } from "@/api/stories";
import { StoryCard } from "./StoryCard";
import { TrendingStoriesSkeleton } from "./StoryItemSkeleton";

const CARD_MIN_WIDTH = 320;

export function TrendingStories() {
  const { t } = useTranslation();
  const containerRef = useRef<HTMLDivElement>(null);
  const [columns, setColumns] = useState(3);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry) return;
      const width = entry.contentRect.width;
      setColumns(Math.max(1, Math.floor(width / CARD_MIN_WIDTH)));
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const { data: stories, isLoading } = useQuery({
    queryKey: ["trendingStories", columns],
    queryFn: () => getTrendingStories(columns),
    staleTime: 2 * 60 * 1000,
  });

  if (isLoading) {
    return <TrendingStoriesSkeleton containerRef={containerRef} />;
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
      <div
        ref={containerRef}
        className="grid gap-2"
        style={{
          gridTemplateColumns: `repeat(auto-fill, minmax(${CARD_MIN_WIDTH}px, 1fr))`,
        }}
      >
        {stories.map((story) => (
          <StoryCard key={story.id} story={story} />
        ))}
      </div>
    </section>
  );
}
