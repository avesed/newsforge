import apiClient from "./client";
import type { Article, PaginatedResponse } from "@/types";

export async function getArticles(
  category?: string,
  page: number = 1,
  pageSize: number = 20,
  hasMarketImpact?: boolean
): Promise<PaginatedResponse<Article>> {
  const params: Record<string, string | number | boolean> = { page, page_size: pageSize };
  if (category) {
    params.category = category;
  }
  if (hasMarketImpact != null) {
    params.has_market_impact = hasMarketImpact;
  }
  const response = await apiClient.get<PaginatedResponse<Article>>("/news", {
    params,
  });
  return response.data;
}

export async function getArticle(id: string): Promise<Article> {
  const response = await apiClient.get<Article>(`/articles/${id}`);
  return response.data;
}

export async function getRelatedArticles(
  articleId: string,
  limit = 6
): Promise<Article[]> {
  const response = await apiClient.get<Article[]>(
    `/articles/${articleId}/related`,
    { params: { limit } }
  );
  return response.data;
}

export async function searchArticles(
  query: string,
  page: number = 1,
  pageSize: number = 20
): Promise<PaginatedResponse<Article>> {
  const response = await apiClient.get<PaginatedResponse<Article>>("/articles/search", {
    params: { q: query, page, page_size: pageSize },
  });
  return response.data;
}
