export interface User {
  id: number;
  email: string;
  displayName: string;
  role: "admin" | "user";
  createdAt: string;
}

export interface Category {
  slug: string;
  name: string;
  nameZh: string;
  color: string;
  icon: string;
}

export interface CategoryDetail {
  slug: string;
  confidence: number;
}

export interface Article {
  id: string;
  title: string;
  summary: string;
  aiSummary: string | null;
  detailedSummary: string | null;
  content: string | null;
  aiAnalysis: string | null;
  hasAiAnalysis: boolean;
  fullText: string | null;
  titleZh: string | null;
  fullTextZh: string | null;
  sourceUrl: string;
  sourceName: string;
  imageUrl: string | null;
  primaryCategory: string | null;
  categories: string[] | null;
  categoryDetails: CategoryDetail[] | null;
  sentimentScore: number | null;
  sentimentLabel: "positive" | "neutral" | "negative" | null;
  valueScore: number | null;
  hasMarketImpact: boolean;
  marketImpactHint: string | null;
  primaryEntityType: string | null;
  processingPath: string | null;
  agentsExecuted: string[] | null;
  storyId: string | null;
  eventGroupId: string | null;
  eventGroupArticles: EventGroupItem[] | null;
  publishedAt: string;
  createdAt: string;
}

export interface EventGroupItem {
  id: string;
  title: string;
  sourceName: string | null;
  publishedAt: string | null;
}

export interface Feed {
  id: string;
  name: string;
  url: string;
  category: string;
  isEnabled: boolean;
  lastFetchedAt: string | null;
  createdAt: string;
}

export interface PaginatedResponse<T> {
  articles: T[];
  total: number;
  page: number;
  pageSize: number;
  hasMore: boolean;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface RegisterRequest {
  email: string;
  password: string;
  displayName: string;
}

export interface AuthResponse {
  accessToken: string;
  refreshToken: string;
  tokenType: string;
}

export interface ReadingHistoryEntry {
  articleId: string;
  readAt: string;
  readDurationMs: number | null;
  article: Article;
}

export interface ApiError {
  detail: string;
}

// Search types

export interface SearchResponse {
  articles: Article[];
  total: number;
  page: number;
  pageSize: number;
  hasMore: boolean;
  searchMode: string;
  queryTimeMs: number;
}

export interface SearchSuggestion {
  title: string;
  articleId: string;
  score: number;
}

export interface SuggestResponse {
  suggestions: SearchSuggestion[];
}

export interface ExternalSearchResult {
  title: string;
  url: string;
  sourceName: string;
  publishedAt: string | null;
  summary: string | null;
  provider: string;
}

export interface ExternalSearchResponse {
  results: ExternalSearchResult[];
  total: number;
  queryTimeMs: number;
}

export interface ImportResponse {
  imported: number;
  articleIds: string[];
}

export type CategorySlug =
  | "finance"
  | "tech"
  | "politics"
  | "entertainment"
  | "gaming"
  | "sports"
  | "world"
  | "science"
  | "health"
  | "other";

export const CATEGORY_COLORS: Record<CategorySlug, string> = {
  finance: "#10b981",
  tech: "#3b82f6",
  politics: "#ef4444",
  entertainment: "#f59e0b",
  gaming: "#8b5cf6",
  sports: "#06b6d4",
  world: "#6366f1",
  science: "#14b8a6",
  health: "#ec4899",
  other: "#6b7280",
};

// Admin types

export interface DashboardStats {
  overview: {
    articlesTotal: number;
    articlesToday: number;
    articlesThisWeek: number;
    storiesActive: number;
    usersTotal: number;
    consumersActive: number;
  };
  categoryDistribution: Record<string, number>;
  hourlyCounts: { hour: string; count: number }[];
  dailyCounts: { date: string; count: number }[];
  sourceHealth: {
    sourceId: string;
    name: string;
    isEnabled: boolean;
    healthStatus: string;
    consecutiveErrors: number;
    articleCount: number;
  }[];
  pipelinePerformance: {
    avgDurationMs: number;
    successRate: number;
    eventsLast24h: number;
    errorCount24h: number;
  };
  topEntities: { entity: string; type: string; mentionCount: number }[];
  sentimentDistribution: { positive: number; neutral: number; negative: number };
  queue: { main: number; retry: number; deadLetter: number };
}

export interface AdminSource {
  id: string;
  name: string;
  sourceType: string;
  provider: string;
  categories: string[] | null;
  markets: string[] | null;
  isEnabled: boolean;
  healthStatus: string;
  consecutiveErrors: number;
  articleCount: number;
}

export interface AdminFeed {
  id: string;
  url: string;
  title: string | null;
  feedType: string;
  rsshubRoute: string | null;
  sourceId: string | null;
  categoryId: string | null;
  categorySlug: string | null;
  pollIntervalMinutes: number;
  fulltextMode: boolean;
  isEnabled: boolean;
  lastPolledAt: string | null;
  consecutiveErrors: number;
  articleCount: number;
  lastError: string | null;
  userId: number | null;
}

export interface AdminConsumer {
  id: string;
  name: string;
  apiKeyPrefix: string;
  description: string | null;
  isActive: boolean;
  rateLimit: number;
  allowedEndpoints: string[] | null;
  lastUsedAt: string | null;
  createdAt: string;
}

export interface PipelineEvent {
  id: string;
  articleId: string;
  stage: string;
  status: string;
  durationMs: number | null;
  error: string | null;
  createdAt: string;
}

export interface LLMProvider {
  id: string;
  name: string;
  providerType: string;
  apiBase: string;
  defaultModel: string;
  embeddingModel: string | null;
  purposeModels: Record<string, string> | null;
  extraParams: Record<string, unknown> | null;
  isEnabled: boolean;
  isDefault: boolean;
  priority: number;
  apiKeyMasked: string;
  createdAt: string;
}

export interface LLMProviderCreate {
  name: string;
  providerType: string;
  apiKey: string;
  apiBase: string;
  defaultModel: string;
  embeddingModel?: string;
  extraParams?: Record<string, unknown>;
  purposeModels?: Record<string, string>;
}

export const ALL_CATEGORIES: Category[] = [
  { slug: "finance", name: "Finance", nameZh: "\u8d22\u7ecf", color: "#10b981", icon: "trending-up" },
  { slug: "tech", name: "Technology", nameZh: "\u79d1\u6280", color: "#3b82f6", icon: "cpu" },
  { slug: "politics", name: "Politics", nameZh: "\u653f\u6cbb", color: "#ef4444", icon: "landmark" },
  { slug: "entertainment", name: "Entertainment", nameZh: "\u5a31\u4e50", color: "#f59e0b", icon: "clapperboard" },
  { slug: "gaming", name: "Gaming", nameZh: "\u6e38\u620f", color: "#8b5cf6", icon: "gamepad-2" },
  { slug: "sports", name: "Sports", nameZh: "\u4f53\u80b2", color: "#06b6d4", icon: "trophy" },
  { slug: "world", name: "World", nameZh: "\u56fd\u9645", color: "#6366f1", icon: "globe" },
  { slug: "science", name: "Science", nameZh: "\u79d1\u5b66", color: "#14b8a6", icon: "flask-conical" },
  { slug: "health", name: "Health", nameZh: "\u5065\u5eb7", color: "#ec4899", icon: "heart-pulse" },
  { slug: "other", name: "Other", nameZh: "\u5176\u4ed6", color: "#6b7280", icon: "newspaper" },
];
