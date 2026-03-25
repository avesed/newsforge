import apiClient from "./client";
import type { PaginatedResponse, Article } from "@/types";

export async function markAsRead(articleId: string, readDurationMs?: number): Promise<void> {
  await apiClient.post(
    `/reading-history/${articleId}`,
    readDurationMs != null ? { readDurationMs } : undefined
  );
}

export async function getReadingHistory(page = 1, pageSize = 20): Promise<PaginatedResponse<Article>> {
  const response = await apiClient.get<PaginatedResponse<Article>>("/reading-history", {
    params: { page, page_size: pageSize },
  });
  return response.data;
}

export async function getReadArticleIds(since?: string): Promise<string[]> {
  const params: Record<string, string> = {};
  if (since) params.since = since;
  const response = await apiClient.get<{ articleIds: string[] }>(
    "/reading-history/ids",
    { params }
  );
  return response.data.articleIds;
}
