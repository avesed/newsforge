import { useEffect, useRef, useCallback, useMemo, useState } from "react";
import { useInfiniteQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Loader2, Newspaper } from "lucide-react";
import { getArticles } from "@/api/articles";
import { ArticleCard } from "./ArticleCard";
import { ArticleListSkeleton } from "./ArticleCardSkeleton";
import { EmptyState } from "@/components/EmptyState";
import { useReadHistory } from "@/hooks/useReadHistory";
import { useIsMobile } from "@/hooks/useIsMobile";
import { usePullToRefresh } from "@/hooks/usePullToRefresh";
import { useStreamingFeed } from "@/hooks/useStreamingFeed";
import { cn } from "@/lib/utils";

const STREAM_ANIMATION_MS = 400;

interface ArticleListProps {
  category?: string | undefined;
}

export function ArticleList({ category }: ArticleListProps) {
  const { t } = useTranslation();
  const { isRead, markRead } = useReadHistory();
  const isMobile = useIsMobile();
  const loadMoreRef = useRef<HTMLDivElement>(null);

  const {
    data,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
    isLoading,
    isError,
    refetch,
  } = useInfiniteQuery({
    queryKey: ["articles", category],
    queryFn: ({ pageParam }) => getArticles(category, pageParam),
    initialPageParam: 1,
    getNextPageParam: (lastPage) =>
      lastPage.hasMore ? lastPage.page + 1 : undefined,
    staleTime: 5 * 60 * 1000,
  });

  // Must be before any early returns to satisfy Rules of Hooks
  const firstPageSize = data?.pages[0]?.articles.length ?? 0;
  const animateUpTo = useMemo(() => firstPageSize, [firstPageSize]);

  const queryClient = useQueryClient();
  const { containerRef, indicatorRef, isRefreshing } = usePullToRefresh({
    onRefresh: async () => {
      await queryClient.invalidateQueries({ queryKey: ["articles", category] });
    },
  });

  // Tracks article IDs that just streamed in, so we can play the slide-in
  // animation exactly once. Cleared after the animation finishes.
  const [streamedIds, setStreamedIds] = useState<Set<string>>(() => new Set());

  useStreamingFeed({
    category,
    enabled: !isLoading && !isError,
    onNewArticles: (ids) => {
      setStreamedIds((prev) => {
        const next = new Set(prev);
        ids.forEach((id) => next.add(id));
        return next;
      });
      window.setTimeout(() => {
        setStreamedIds((prev) => {
          if (prev.size === 0) return prev;
          const next = new Set(prev);
          ids.forEach((id) => next.delete(id));
          return next;
        });
      }, STREAM_ANIMATION_MS);
    },
  });

  const handleObserver = useCallback(
    (entries: IntersectionObserverEntry[]) => {
      const first = entries[0];
      if (first?.isIntersecting && hasNextPage && !isFetchingNextPage) {
        void fetchNextPage();
      }
    },
    [fetchNextPage, hasNextPage, isFetchingNextPage]
  );

  useEffect(() => {
    const node = loadMoreRef.current;
    if (!node) return;
    const observer = new IntersectionObserver(handleObserver, {
      rootMargin: "200px",
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, [handleObserver]);

  if (isLoading) {
    return <ArticleListSkeleton />;
  }

  if (isError) {
    return (
      <div className="flex flex-col items-center justify-center py-12">
        <p className="text-muted-foreground">{t("common.error")}</p>
        <button
          onClick={() => void refetch()}
          className="mt-2 rounded-md bg-primary px-4 py-2 text-sm text-primary-foreground"
        >
          {t("common.retry")}
        </button>
      </div>
    );
  }

  const articles = data?.pages.flatMap((page) => page.articles) ?? [];

  if (articles.length === 0) {
    return (
      <EmptyState
        icon={Newspaper}
        title={t("article.noArticles")}
        description={t("article.noArticlesHint")}
      />
    );
  }

  return (
    <div ref={containerRef}>
      {/* Pull-to-refresh indicator — height controlled by DOM ref, not React state */}
      <div
        ref={indicatorRef}
        className="flex items-center justify-center overflow-hidden"
        style={{ height: 0, opacity: 0 }}
      >
        <Loader2
          data-pull-icon
          className={cn(
            "h-5 w-5 text-primary",
            isRefreshing && "animate-spin"
          )}
        />
      </div>
      <div className="flex flex-col">
        {articles.map((article, index) => {
          const isHero = isMobile && index === 0 && !!article.imageUrl;
          const isStreamed = streamedIds.has(article.id);
          // Skip stagger animation on hero card — it has its own visual presence.
          // Streamed-in items get their own slide-in that overrides the stagger.
          const shouldStagger = !isStreamed && index < animateUpTo && !isHero;
          const animClass = isStreamed
            ? "animate-stream-in"
            : shouldStagger
            ? "animate-stagger-item"
            : undefined;
          return (
            <div
              key={article.id}
              className={animClass}
              style={
                shouldStagger
                  ? { animationDelay: `${Math.min(index * 50, 500)}ms` }
                  : undefined
              }
            >
              <ArticleCard
                article={article}
                isRead={isRead(article.id)}
                onMarkRead={(id) => void markRead(id)}
                variant={isHero ? "hero" : "standard"}
              />
            </div>
          );
        })}
        <div ref={loadMoreRef} className="py-4 text-center">
          {isFetchingNextPage && (
            <div className="flex items-center justify-center gap-2">
              <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
              <span className="text-sm text-muted-foreground">
                {t("article.loading")}
              </span>
            </div>
          )}
        </div>
        {!hasNextPage && articles.length > 0 && !isFetchingNextPage && (
          <div className="flex items-center gap-3 py-6 text-xs text-muted-foreground">
            <div className="h-px flex-1 bg-border" />
            <span>{t("article.noMore")}</span>
            <div className="h-px flex-1 bg-border" />
          </div>
        )}
      </div>
    </div>
  );
}
