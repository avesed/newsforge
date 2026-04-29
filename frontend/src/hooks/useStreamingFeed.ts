import { useEffect, useRef } from "react";
import { useQueryClient, type InfiniteData } from "@tanstack/react-query";
import { getNewArticlesSince } from "@/api/articles";
import type { Article, PaginatedResponse } from "@/types";

const POLL_INTERVAL_MS = 60_000;

type ArticlesInfinite = InfiniteData<PaginatedResponse<Article>>;

interface Options {
  /** Category slug currently displayed (matches the React Query key). */
  category?: string | undefined;
  /** Set to false to disable polling (e.g. for non-feed pages). */
  enabled?: boolean | undefined;
  /** Notified with the IDs of articles newly merged into the cache, for animation. */
  onNewArticles?: ((ids: string[]) => void) | undefined;
}

/**
 * Polls the server for newly ingested articles and merges them into the top of
 * the React Query infinite-list cache for `["articles", category]`. The list
 * re-renders incrementally — no full refetch, no scroll-jump (browsers anchor
 * scrollY when prepending DOM above the viewport).
 *
 * Pauses while the document is hidden; runs immediately when it becomes visible
 * again so users returning to the tab see fresh news right away.
 */
export function useStreamingFeed({
  category,
  enabled = true,
  onNewArticles,
}: Options) {
  const queryClient = useQueryClient();
  const lastSeenRef = useRef<string | null>(null);
  const inFlightRef = useRef(false);
  const onNewRef = useRef(onNewArticles);

  // Keep callback ref fresh without re-running the effect.
  useEffect(() => {
    onNewRef.current = onNewArticles;
  }, [onNewArticles]);

  useEffect(() => {
    if (!enabled) return;

    const queryKey = ["articles", category] as const;
    let cancelled = false;

    // Reset baseline whenever the category changes — avoids carrying a stale
    // cursor from another tab.
    lastSeenRef.current = null;

    const readBaseline = (): string | null => {
      const cache = queryClient.getQueryData<ArticlesInfinite>(queryKey);
      const first = cache?.pages?.[0]?.articles?.[0];
      return first?.createdAt ?? null;
    };

    const poll = async () => {
      if (cancelled || inFlightRef.current) return;
      if (typeof document !== "undefined" && document.hidden) return;

      // First run after mount — baseline from current cache.
      if (!lastSeenRef.current) {
        lastSeenRef.current = readBaseline();
        if (!lastSeenRef.current) return; // List not loaded yet; try again later.
      }

      inFlightRef.current = true;
      try {
        const resp = await getNewArticlesSince(lastSeenRef.current, category);
        const incoming = resp.articles;
        if (incoming.length === 0) return;

        let mergedIds: string[] = [];
        queryClient.setQueryData<ArticlesInfinite>(queryKey, (old) => {
          if (!old || old.pages.length === 0) return old;
          const firstPage = old.pages[0];
          if (!firstPage) return old;

          const seen = new Set<string>();
          for (const page of old.pages) {
            for (const a of page.articles) seen.add(a.id);
          }
          const fresh = incoming.filter((a) => !seen.has(a.id));
          if (fresh.length === 0) return old;

          mergedIds = fresh.map((a) => a.id);
          const newFirst: PaginatedResponse<Article> = {
            ...firstPage,
            articles: [...fresh, ...firstPage.articles],
            total: firstPage.total + fresh.length,
          };
          return { ...old, pages: [newFirst, ...old.pages.slice(1)] };
        });

        // Advance cursor to the newest item the server returned. If everything
        // was a duplicate, still advance past the response's newest to avoid
        // re-fetching the same window.
        const newest = incoming[0];
        if (newest) lastSeenRef.current = newest.createdAt;
        if (mergedIds.length > 0) onNewRef.current?.(mergedIds);
      } catch {
        // Network/server hiccup — keep cursor, retry next tick.
      } finally {
        inFlightRef.current = false;
      }
    };

    const intervalId = window.setInterval(() => void poll(), POLL_INTERVAL_MS);
    const onVisibility = () => {
      if (!document.hidden) void poll();
    };
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [category, enabled, queryClient]);
}
