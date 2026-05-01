import apiClient from "./client";

// --- Dashboard ---

export async function getDashboardStats() {
  const res = await apiClient.get("/admin/stats/dashboard");
  return res.data as DashboardStatsRaw;
}

// --- Pipeline ---

export async function getPipelineStats() {
  const res = await apiClient.get("/admin/pipeline/stats");
  return res.data as PipelineStatsRaw;
}

export async function getPipelineEvents(params?: {
  limit?: number | undefined;
  stage?: string | undefined;
  articleId?: string | undefined;
}) {
  const res = await apiClient.get("/admin/pipeline/events", {
    params: {
      limit: params?.limit,
      stage: params?.stage,
      article_id: params?.articleId,
    },
  });
  return res.data as PipelineEventRaw[];
}

export async function triggerPoll() {
  const res = await apiClient.post("/admin/pipeline/trigger-poll");
  return res.data as { status: string };
}

// --- Sources ---

export async function getSources() {
  const res = await apiClient.get("/admin/sources");
  return res.data as SourceRaw[];
}

export async function createSource(data: {
  name: string;
  sourceType: string;
  provider: string;
  config?: Record<string, unknown>;
}) {
  const res = await apiClient.post("/admin/sources", {
    name: data.name,
    source_type: data.sourceType,
    provider: data.provider,
    config: data.config,
  });
  return res.data as SourceRaw;
}

export async function updateSource(
  id: string,
  data: { isEnabled?: boolean; name?: string },
) {
  const res = await apiClient.patch(`/admin/sources/${id}`, {
    is_enabled: data.isEnabled,
    name: data.name,
  });
  return res.data as SourceRaw;
}

export async function deleteSource(id: string) {
  await apiClient.delete(`/admin/sources/${id}`);
}

export async function getAllFeeds() {
  const res = await apiClient.get("/admin/sources/feeds");
  return res.data as AdminFeedRaw[];
}

export async function createAdminFeed(data: {
  url: string;
  title?: string | undefined;
  feedType?: string | undefined;
  rsshubRoute?: string | undefined;
  categorySlug?: string | undefined;
  pollIntervalMinutes?: number | undefined;
  fulltextMode?: boolean | undefined;
}) {
  const res = await apiClient.post("/admin/sources/feeds", {
    url: data.url,
    title: data.title,
    feed_type: data.feedType ?? "native_rss",
    rsshub_route: data.rsshubRoute,
    category_slug: data.categorySlug,
    poll_interval_minutes: data.pollIntervalMinutes ?? 15,
    fulltext_mode: data.fulltextMode ?? false,
  });
  return res.data as AdminFeedRaw;
}

export async function updateAdminFeed(
  id: string,
  data: {
    isEnabled?: boolean | undefined;
    title?: string | undefined;
    pollIntervalMinutes?: number | undefined;
    fulltextMode?: boolean | undefined;
    categorySlug?: string | undefined;
  },
) {
  const res = await apiClient.patch(`/admin/sources/feeds/${id}`, {
    is_enabled: data.isEnabled,
    title: data.title,
    poll_interval_minutes: data.pollIntervalMinutes,
    fulltext_mode: data.fulltextMode,
    category_slug: data.categorySlug,
  });
  return res.data as AdminFeedRaw;
}

export async function deleteAdminFeed(id: string) {
  await apiClient.delete(`/admin/sources/feeds/${id}`);
}

export async function testAdminFeed(id: string) {
  const res = await apiClient.post(`/admin/sources/feeds/${id}/test`);
  return res.data as { success: boolean; message: string; articleCount: number };
}

// --- Google News Options ---

export interface GoogleNewsOption {
  id: string;
  labelEn: string;
  labelZh: string;
  category?: string;
}

export interface GoogleNewsOptions {
  topics: GoogleNewsOption[];
  locales: GoogleNewsOption[];
}

export async function getGoogleNewsOptions(): Promise<GoogleNewsOptions> {
  const response = await apiClient.get("/admin/sources/google-news/options");
  // Backend returns snake_case (label_en, label_zh), convert to camelCase
  const raw = response.data as {
    topics: { id: string; label_en: string; label_zh: string; category?: string }[];
    locales: { id: string; label_en: string; label_zh: string }[];
  };
  return {
    topics: raw.topics.map((t) => {
      const o: GoogleNewsOption = { id: t.id, labelEn: t.label_en, labelZh: t.label_zh };
      if (t.category) o.category = t.category;
      return o;
    }),
    locales: raw.locales.map((l) => ({ id: l.id, labelEn: l.label_en, labelZh: l.label_zh })),
  };
}

export async function buildGoogleNewsUrl(topic: string, locale: string) {
  const response = await apiClient.post("/admin/sources/google-news/build-url", { topic, locale });
  return response.data as { url: string; title: string; category: string | null };
}

// --- Consumers ---

export async function getConsumers() {
  const res = await apiClient.get("/admin/consumers");
  return res.data as ConsumerRaw[];
}

export async function createConsumer(data: {
  name: string;
  description?: string | undefined;
}) {
  const res = await apiClient.post("/admin/consumers", data);
  return res.data as ConsumerCreateRaw;
}

export async function deleteConsumer(id: string) {
  await apiClient.delete(`/admin/consumers/${id}`);
}

export async function getConsumerUsage(consumerId: string) {
  const res = await apiClient.get(`/admin/consumers/${consumerId}/usage`);
  return res.data as ConsumerUsageRaw;
}

export async function testConsumerWebhook(consumerId: string, webhookId: string) {
  const res = await apiClient.post(
    `/admin/consumers/${consumerId}/webhooks/${webhookId}/test`,
  );
  return res.data as { success: boolean; statusCode: number | null; responseBody: string | null; error: string | null };
}

// --- LLM Providers ---

export async function getLLMProviders() {
  const res = await apiClient.get("/admin/llm/providers");
  return res.data as LLMProviderRaw[];
}

export async function createLLMProvider(data: {
  name: string;
  providerType: string;
  apiKey: string;
  apiBase: string;
  defaultModel: string;
  embeddingModel?: string;
  extraParams?: Record<string, unknown>;
  purposeModels?: Record<string, string>;
}) {
  const res = await apiClient.post("/admin/llm/providers", {
    name: data.name,
    provider_type: data.providerType,
    api_key: data.apiKey,
    api_base: data.apiBase,
    default_model: data.defaultModel,
    embedding_model: data.embeddingModel,
    extra_params: data.extraParams,
    purpose_models: data.purposeModels,
  });
  return res.data as LLMProviderRaw;
}

export async function updateLLMProvider(
  id: string,
  data: {
    name?: string;
    providerType?: string;
    apiKey?: string;
    apiBase?: string;
    defaultModel?: string;
    embeddingModel?: string;
    extraParams?: Record<string, unknown> | null;
    purposeModels?: Record<string, string> | null;
    isEnabled?: boolean;
  },
) {
  const res = await apiClient.patch(`/admin/llm/providers/${id}`, {
    name: data.name,
    provider_type: data.providerType,
    api_key: data.apiKey,
    api_base: data.apiBase,
    default_model: data.defaultModel,
    embedding_model: data.embeddingModel,
    extra_params: data.extraParams,
    purpose_models: data.purposeModels,
    is_enabled: data.isEnabled,
  });
  return res.data as LLMProviderRaw;
}

export async function deleteLLMProvider(id: string) {
  await apiClient.delete(`/admin/llm/providers/${id}`);
}

export async function testLLMProvider(id: string) {
  const res = await apiClient.post(`/admin/llm/providers/${id}/test`);
  return res.data as { success: boolean; message: string };
}

export async function testLLMConnection(data: {
  apiKey: string;
  apiBase: string;
  defaultModel: string;
}) {
  const res = await apiClient.post("/admin/llm/providers/test", {
    api_key: data.apiKey,
    api_base: data.apiBase,
    default_model: data.defaultModel,
  });
  return res.data as { success: boolean; message: string };
}

export async function setDefaultProvider(id: string) {
  const res = await apiClient.put(`/admin/llm/providers/${id}/default`);
  return res.data as LLMProviderRaw;
}

// --- LLM Profiles ---

export async function getLLMProfiles() {
  const res = await apiClient.get("/admin/llm/profiles");
  return res.data as LLMProfileRaw[];
}

export async function createLLMProfile(data: {
  name: string;
  description?: string | undefined;
  temperature?: number | null | undefined;
  maxTokens?: number | null | undefined;
  topP?: number | null | undefined;
  thinkingEnabled?: boolean | null | undefined;
  thinkingBudgetTokens?: number | null | undefined;
  timeoutSeconds?: number | null | undefined;
  maxRetries?: number | null | undefined;
  extraParams?: Record<string, unknown> | undefined;
}) {
  const res = await apiClient.post("/admin/llm/profiles", {
    name: data.name,
    description: data.description,
    temperature: data.temperature,
    max_tokens: data.maxTokens,
    top_p: data.topP,
    thinking_enabled: data.thinkingEnabled,
    thinking_budget_tokens: data.thinkingBudgetTokens,
    timeout_seconds: data.timeoutSeconds,
    max_retries: data.maxRetries,
    extra_params: data.extraParams,
  });
  return res.data as LLMProfileRaw;
}

export async function updateLLMProfile(
  id: string,
  data: {
    name?: string | undefined;
    description?: string | null | undefined;
    temperature?: number | null | undefined;
    maxTokens?: number | null | undefined;
    topP?: number | null | undefined;
    thinkingEnabled?: boolean | null | undefined;
    thinkingBudgetTokens?: number | null | undefined;
    timeoutSeconds?: number | null | undefined;
    maxRetries?: number | null | undefined;
    extraParams?: Record<string, unknown> | null | undefined;
  },
) {
  const res = await apiClient.patch(`/admin/llm/profiles/${id}`, {
    name: data.name,
    description: data.description,
    temperature: data.temperature,
    max_tokens: data.maxTokens,
    top_p: data.topP,
    thinking_enabled: data.thinkingEnabled,
    thinking_budget_tokens: data.thinkingBudgetTokens,
    timeout_seconds: data.timeoutSeconds,
    max_retries: data.maxRetries,
    extra_params: data.extraParams,
  });
  return res.data as LLMProfileRaw;
}

export async function deleteLLMProfile(id: string) {
  await apiClient.delete(`/admin/llm/profiles/${id}`);
}

// --- Agent LLM Config ---

export async function getAgentConfigs() {
  const res = await apiClient.get("/admin/llm/agents");
  return res.data as AgentConfigListRaw;
}

export async function upsertAgentConfig(
  agentId: string,
  data: {
    providerId?: string | null;
    model?: string | null;
    profileId?: string | null;
  },
) {
  const res = await apiClient.put(`/admin/llm/agents/${agentId}`, {
    provider_id: data.providerId,
    model: data.model,
    profile_id: data.profileId,
  });
  return res.data as AgentConfigRaw;
}

export async function deleteAgentConfig(agentId: string) {
  await apiClient.delete(`/admin/llm/agents/${agentId}`);
}

export async function checkLLMHealth() {
  const res = await apiClient.get("/health/llm");
  return res.data as { configured: boolean; status: string };
}

// --- Queue Monitoring ---

export interface AgentProgress {
  success: boolean;
  duration_ms: number;
  tokens_used: number;
  error?: string;
}

export interface QueueArticle {
  article_id: string;
  title: string;
  status?: string;
  current_stage?: string;
  enqueued_at?: string;
  started_at?: string;
  completed_at?: string;
  duration_ms?: string;
  error?: string;
  position?: number;
  priority?: string;
  agent_progress?: Record<string, AgentProgress>;
  current_agent?: string;
}

export interface CircuitBreakerPurposeState {
  purpose: string;
  state: "open" | "closed";
  consecutiveFailures: number;
  lastFailureTime: number;
  lastProbeTime: number;
  lastSuccessTime: number;
  updatedAt?: number;
}

export interface CircuitBreakerStatus {
  state: "open" | "closed";
  consecutiveFailures: number;
  openPurposes: string[];
  purposes: CircuitBreakerPurposeState[];
}

export interface QueueStatus {
  queued: QueueArticle[];
  queued_high?: QueueArticle[];
  queued_low?: QueueArticle[];
  processing: QueueArticle[];
  recent: QueueArticle[];
  counts: { queued: number; queued_high?: number; queued_low?: number; processing: number; completed: number; failed: number; dead_letter: number; retry: number };
  concurrency: { active: number; target: number };
  paused: boolean;
  circuitBreaker?: CircuitBreakerStatus;
}

export async function getQueueStatus(): Promise<QueueStatus> {
  const res = await apiClient.get("/admin/pipeline/queue");
  return res.data;
}

export interface QueueItemsResponse {
  items: QueueArticle[];
  total: number;
  page: number;
  page_size: number;
}

export async function getQueueItems(page: number, pageSize: number): Promise<QueueItemsResponse> {
  const res = await apiClient.get("/admin/pipeline/queue/items", {
    params: { page, page_size: pageSize },
  });
  return res.data;
}

export async function getRecentItems(page: number, pageSize: number): Promise<QueueItemsResponse> {
  const res = await apiClient.get("/admin/pipeline/queue/recent", {
    params: { page, page_size: pageSize },
  });
  return res.data;
}

export async function getConcurrency() {
  const res = await apiClient.get("/admin/pipeline/concurrency");
  return res.data as { active: number; target: number; default: number };
}

export async function setConcurrency(concurrency: number) {
  const res = await apiClient.put("/admin/pipeline/concurrency", { concurrency });
  return res.data;
}

export async function pausePipeline() {
  const res = await apiClient.put("/admin/pipeline/pause");
  return res.data;
}

export async function resumePipeline() {
  const res = await apiClient.put("/admin/pipeline/resume");
  return res.data;
}

export async function getCircuitBreakerStatus(): Promise<
  CircuitBreakerStatus & { failureThreshold: number; recoveryTimeout: number }
> {
  const res = await apiClient.get("/admin/pipeline/circuit-breaker");
  return res.data;
}

export async function resetCircuitBreaker(purpose?: string) {
  const res = await apiClient.post(
    "/admin/pipeline/circuit-breaker/reset",
    purpose ? { purpose } : {},
  );
  return res.data;
}

// --- Agent Priority ---

export interface AgentPriorityAgent {
  agentId: string;
  name: string;
  description: string;
  tier: "p1" | "p2";
  requires: string[];
}

export interface AgentPriorityConfig {
  p2Enabled: boolean;
  agents: AgentPriorityAgent[];
}

export async function getAgentPriority(): Promise<AgentPriorityConfig> {
  const res = await apiClient.get("/admin/pipeline/agent-priority");
  // Backend returns snake_case; manually map to camelCase
  const raw = res.data as {
    p2_enabled: boolean;
    agents: { agent_id: string; name: string; description: string; tier: "p1" | "p2"; requires: string[] }[];
  };
  return {
    p2Enabled: raw.p2_enabled,
    agents: raw.agents.map((a) => ({
      agentId: a.agent_id,
      name: a.name,
      description: a.description,
      tier: a.tier,
      requires: a.requires,
    })),
  };
}

export async function updateAgentPriority(data: {
  p2Enabled: boolean;
  p1Agents: string[];
}) {
  const res = await apiClient.put("/admin/pipeline/agent-priority", {
    p2_enabled: data.p2Enabled,
    p1_agents: data.p1Agents,
  });
  return res.data;
}

// --- Import/Export ---

export interface ImportResult {
  total: number;
  imported: number;
  duplicates: number;
  errors: number;
  errorDetails: string[];
}

export async function importArticles(file: File): Promise<ImportResult> {
  const formData = new FormData();
  formData.append("file", file);
  const res = await apiClient.post("/admin/articles/import", formData, {
    headers: { "Content-Type": "multipart/form-data" },
    timeout: 300000, // 5 minutes for large files
  });
  return res.data as ImportResult;
}

// --- LLM Profile & Agent Config types ---

export interface LLMProfileRaw {
  id: string;
  name: string;
  description: string | null;
  temperature: number | null;
  maxTokens: number | null;
  topP: number | null;
  thinkingEnabled: boolean | null;
  thinkingBudgetTokens: number | null;
  timeoutSeconds: number | null;
  maxRetries: number | null;
  extraParams: Record<string, unknown> | null;
  createdAt: string;
  updatedAt: string;
}

export interface AgentConfigRaw {
  id: string;
  agentId: string;
  providerId: string | null;
  providerName: string | null;
  model: string | null;
  profileId: string | null;
  profileName: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface AgentConfigListRaw {
  configs: AgentConfigRaw[];
  registeredAgents: string[];
}

// --- Raw response types (snake_case from backend) ---

export interface DashboardStatsRaw {
  overview: {
    articles_total: number;
    articles_today: number;
    articles_this_week: number;
    stories_active: number;
    users_total: number;
    consumers_active: number;
  };
  category_distribution: Record<string, number>;
  hourly_counts: { hour: string; count: number }[];
  daily_counts: { date: string; count: number }[];
  source_health: {
    source_id: string;
    name: string;
    is_enabled: boolean;
    health_status: string;
    consecutive_errors: number;
    article_count: number;
    last_fetched_at: string | null;
  }[];
  pipeline_performance: {
    avg_duration_ms: number;
    success_rate: number;
    events_last_24h: number;
    error_count_24h: number;
  };
  top_entities: { entity: string; type: string; mention_count: number }[];
  sentiment_distribution: {
    positive: number;
    neutral: number;
    negative: number;
  };
  queue: { main: number; high?: number; low?: number; retry: number; dead_letter: number };
}

export interface PipelineStatsRaw {
  article_status: Record<string, number>;
  category_distribution: Record<string, number>;
  market_impact_count: number;
  value_distribution: { high: number; medium: number; low: number };
  queue: { main: number; high?: number; low?: number; retry: number; dead_letter: number };
}

export interface PipelineEventRaw {
  id: string;
  article_id: string;
  stage: string;
  status: string;
  duration_ms: number | null;
  error: string | null;
  created_at: string;
}

export interface SourceRaw {
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

export interface AdminFeedRaw {
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

export interface ConsumerRaw {
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

export interface ConsumerCreateRaw extends ConsumerRaw {
  rawApiKey: string;
}

export interface WebhookSummaryRaw {
  id: string;
  url: string;
  events: string[];
  isActive: boolean;
  consecutiveFailures: number;
  lastTriggeredAt: string | null;
  createdAt: string | null;
}

export interface ConsumerUsageRaw {
  consumerId: string;
  name: string;
  isActive: boolean;
  lastUsedAt: string | null;
  webhookCount: number;
  webhooks: WebhookSummaryRaw[];
  createdAt: string | null;
}

export interface LLMProviderRaw {
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

// --- Users ---

export interface UserRaw {
  id: number;
  email: string;
  displayName: string | null;
  role: string;
  locale: string;
  isActive: boolean;
  createdAt: string;
  updatedAt: string;
}

export async function getUsers() {
  const res = await apiClient.get("/admin/users");
  return res.data as UserRaw[];
}

export async function updateUser(
  id: number,
  data: { role?: string; isActive?: boolean; displayName?: string },
) {
  const res = await apiClient.patch(`/admin/users/${id}`, {
    role: data.role,
    is_active: data.isActive,
    display_name: data.displayName,
  });
  return res.data as UserRaw;
}

export async function deleteUser(id: number) {
  await apiClient.delete(`/admin/users/${id}`);
}

// --- StockPulse integration ---

export interface StockPulseConfigRaw {
  url: string | null;
  apiKeySet: boolean;
  apiKeyPreview: string | null;
  enabledInYaml: boolean;
  pollIntervalMinutes: number;
  defaultLimit: number;
}

export interface StockPulseTestResultRaw {
  ok: boolean;
  statusCode: number | null;
  message: string;
  elapsedMs: number | null;
}

export interface WatchedSymbolRowRaw {
  id: number;
  symbol: string;
  market: string | null;
  registeredBy: string | null;
  lastViewedAt: string | null;
  lastPolledAt: string | null;
  lastError: string | null;
}

export interface WatchedSymbolsResponseRaw {
  total: number;
  items: WatchedSymbolRowRaw[];
}

export async function getStockPulseConfig() {
  const res = await apiClient.get("/admin/stockpulse/config");
  return res.data as StockPulseConfigRaw;
}

export async function updateStockPulseConfig(data: {
  url?: string | null;
  apiKey?: string | null;
}) {
  const res = await apiClient.put("/admin/stockpulse/config", {
    url: data.url,
    api_key: data.apiKey,
  });
  return res.data as StockPulseConfigRaw;
}

export async function testStockPulseConnection() {
  const res = await apiClient.post("/admin/stockpulse/test");
  return res.data as StockPulseTestResultRaw;
}

export async function getStockPulseWatched(limit = 200) {
  const res = await apiClient.get("/admin/stockpulse/watched", {
    params: { limit },
  });
  return res.data as WatchedSymbolsResponseRaw;
}

export async function triggerStockPulsePoll(tier: "hot" | "warm" | "cold") {
  const res = await apiClient.post(`/admin/stockpulse/poll/${tier}`);
  return res.data as { tier: string; triggered: boolean; message: string };
}
