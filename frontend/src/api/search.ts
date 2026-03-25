import apiClient from "./client";
import type {
  SearchResponse,
  SuggestResponse,
  ExternalSearchResponse,
  ImportResponse,
} from "@/types";

export interface SearchParams {
  q: string;
  category?: string | undefined;
  language?: string | undefined;
  dateFrom?: string | undefined;
  dateTo?: string | undefined;
  hasMarketImpact?: boolean | undefined;
  sort?: "relevance" | "date" | "value_score" | undefined;
  page?: number | undefined;
  pageSize?: number | undefined;
}

export async function searchArticles(
  params: SearchParams
): Promise<SearchResponse> {
  const query: Record<string, string | number | boolean> = { q: params.q };
  if (params.category) query.category = params.category;
  if (params.language) query.language = params.language;
  if (params.dateFrom) query.date_from = params.dateFrom;
  if (params.dateTo) query.date_to = params.dateTo;
  if (params.hasMarketImpact != null)
    query.has_market_impact = params.hasMarketImpact;
  if (params.sort) query.sort = params.sort;
  if (params.page != null) query.page = params.page;
  if (params.pageSize != null) query.page_size = params.pageSize;

  const response = await apiClient.get<SearchResponse>("/search", {
    params: query,
  });
  return response.data;
}

export async function searchSuggest(
  q: string,
  limit?: number
): Promise<SuggestResponse> {
  const params: Record<string, string | number> = { q };
  if (limit != null) params.limit = limit;
  const response = await apiClient.get<SuggestResponse>("/search/suggest", {
    params,
  });
  return response.data;
}

export async function searchExternal(
  q: string,
  locale?: string,
  limit?: number,
  dateFrom?: string,
  dateTo?: string,
): Promise<ExternalSearchResponse> {
  const params: Record<string, string | number> = { q };
  if (locale) params.locale = locale;
  if (limit != null) params.limit = limit;
  if (dateFrom) params.date_from = dateFrom;
  if (dateTo) params.date_to = dateTo;
  const response = await apiClient.get<ExternalSearchResponse>(
    "/search/external",
    { params }
  );
  return response.data;
}

export async function importExternalArticles(
  urls: string[]
): Promise<ImportResponse> {
  const response = await apiClient.post<ImportResponse>(
    "/search/external/import",
    { urls }
  );
  return response.data;
}
