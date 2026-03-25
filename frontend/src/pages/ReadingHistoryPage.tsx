import { useRef, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { useInfiniteQuery } from "@tanstack/react-query";
import { Loader2, History } from "lucide-react";
import { getReadingHistory } from "@/api/readingHistory";
import { ArticleCard } from "@/components/article/ArticleCard";

export default function ReadingHistoryPage() {
  const { t } = useTranslation();
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
    queryKey: ["readingHistory", "list"],
    queryFn: ({ pageParam }) => getReadingHistory(pageParam, 20),
    initialPageParam: 1,
    getNextPageParam: (lastPage) =>
      lastPage.hasMore ? lastPage.page + 1 : undefined,
    staleTime: 2 * 60 * 1000,
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

  const articles = data?.pages.flatMap((page) => page.articles) ?? [];

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-2xl font-bold text-foreground">
        {t("history.title")}
      </h1>

      {isLoading && (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          <span className="ml-2 text-muted-foreground">
            {t("common.loading")}
          </span>
        </div>
      )}

      {isError && (
        <div className="flex flex-col items-center justify-center py-12">
          <p className="text-muted-foreground">{t("common.error")}</p>
          <button
            onClick={() => void refetch()}
            className="mt-2 rounded-md bg-primary px-4 py-2 text-sm text-primary-foreground"
          >
            {t("common.retry")}
          </button>
        </div>
      )}

      {!isLoading && !isError && articles.length === 0 && (
        <div className="flex flex-col items-center justify-center py-16">
          <History className="mb-4 h-12 w-12 text-muted-foreground" />
          <p className="text-muted-foreground">{t("history.empty")}</p>
        </div>
      )}

      {articles.length > 0 && (
        <div className="flex flex-col gap-3">
          {articles.map((article) => (
            <ArticleCard key={article.id} article={article} isRead />
          ))}
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
        </div>
      )}
    </div>
  );
}
