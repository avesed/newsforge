import { useMemo, useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useAuthStore } from "@/stores/authStore";
import { getReadArticleIds, markAsRead } from "@/api/readingHistory";

const THIRTY_DAYS_MS = 30 * 24 * 60 * 60 * 1000;

export function useReadHistory() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated());
  const queryClient = useQueryClient();

  const since = useMemo(
    () => new Date(Date.now() - THIRTY_DAYS_MS).toISOString(),
    []
  );

  const { data: readIds = [] } = useQuery({
    queryKey: ["readHistory", "ids"],
    queryFn: () => getReadArticleIds(since),
    enabled: isAuthenticated,
    staleTime: 5 * 60 * 1000,
  });

  const readSet = useMemo(() => new Set(readIds), [readIds]);

  const isRead = useCallback(
    (id: string) => readSet.has(id),
    [readSet]
  );

  const markRead = useCallback(
    async (id: string) => {
      if (readSet.has(id)) return;

      // Optimistic update
      queryClient.setQueryData<string[]>(
        ["readHistory", "ids"],
        (old) => (old ? [...old, id] : [id])
      );

      try {
        await markAsRead(id);
      } catch {
        // Silent failure — optimistic update stays to avoid flickering
      }
    },
    [readSet, queryClient]
  );

  return { readSet, isRead, markRead };
}
