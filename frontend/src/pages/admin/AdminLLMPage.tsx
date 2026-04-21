import { useState, useEffect, useMemo, useCallback, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Loader2,
  Plus,
  Trash2,
  Pencil,
  Power,
  FlaskConical,
  Cpu,
  Star,
  Settings2,
  Sliders,
  Bot,
  RotateCcw,
  Save,
  Check,
  Layers,
} from "lucide-react";
import {
  getLLMProviders,
  createLLMProvider,
  updateLLMProvider,
  deleteLLMProvider,
  testLLMProvider,
  testLLMConnection,
  setDefaultProvider,
  getLLMProfiles,
  createLLMProfile,
  updateLLMProfile,
  deleteLLMProfile,
  getAgentConfigs,
  upsertAgentConfig,
  deleteAgentConfig,
  getAgentPriority,
  updateAgentPriority,
} from "@/api/admin";
import type {
  LLMProviderRaw,
  LLMProfileRaw,
} from "@/api/admin";
import { getErrorMessage } from "@/api/client";
import { StatusBadge } from "@/components/admin/StatusBadge";
import { AdminLayout } from "@/components/admin/AdminLayout";
import { INPUT_CLASS } from "@/components/admin/utils";

// ---------------------------------------------------------------------------
// LLM Provider Form (create / edit)
// ---------------------------------------------------------------------------
function LLMProviderForm({
  initial,
  onSave,
  onCancel,
  isSaving,
}: {
  initial?: LLMProviderRaw;
  onSave: (data: {
    name: string;
    providerType: string;
    apiKey: string;
    apiBase: string;
    defaultModel: string;
    embeddingModel?: string;
    extraModels?: string[];
    extraParams?: Record<string, unknown>;
  }) => void;
  onCancel: () => void;
  isSaving: boolean;
}) {
  const { t } = useTranslation();
  const [name, setName] = useState(initial?.name ?? "");
  const [providerType, setProviderType] = useState(initial?.providerType ?? "openai");
  const [apiKey, setApiKey] = useState("");
  const [apiBase, setApiBase] = useState(initial?.apiBase ?? "https://api.openai.com/v1");
  const [defaultModel, setDefaultModel] = useState(initial?.defaultModel ?? "gpt-4o-mini");
  const [embeddingModel, setEmbeddingModel] = useState(initial?.embeddingModel ?? "");
  // Extra available models — stored as purposeModels._extra on the provider
  const [extraModelsStr, setExtraModelsStr] = useState(() => {
    const pm = initial?.purposeModels;
    if (pm?._extra) return pm._extra;
    // Also collect any existing purpose model values as initial display
    if (pm) {
      const vals = Object.values(pm).filter(Boolean);
      return vals.length > 0 ? vals.join(", ") : "";
    }
    return "";
  });
  const [extraParamsStr, setExtraParamsStr] = useState(
    initial?.extraParams ? JSON.stringify(initial.extraParams, null, 2) : "",
  );
  const [extraParamsError, setExtraParamsError] = useState("");
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null);
  const [tested, setTested] = useState(false);
  const [isTesting, setIsTesting] = useState(false);

  const handleTest = async () => {
    setIsTesting(true);
    setTestResult(null);
    try {
      const result = await testLLMConnection({
        apiKey: apiKey || "keep-current",
        apiBase,
        defaultModel,
      });
      setTestResult(result);
      setTested(result.success);
    } catch (err) {
      setTestResult({ success: false, message: getErrorMessage(err) });
      setTested(false);
    } finally {
      setIsTesting(false);
    }
  };

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    // Validate extraParams JSON
    let parsedExtra: Record<string, unknown> | undefined;
    if (extraParamsStr.trim()) {
      try {
        parsedExtra = JSON.parse(extraParamsStr.trim()) as Record<string, unknown>;
        setExtraParamsError("");
      } catch {
        setExtraParamsError(t("admin.invalidJson"));
        return;
      }
    }
    // Parse extra models from comma-separated string
    const parsedExtraModels = extraModelsStr
      .split(/[,，\n]/)
      .map((s) => s.trim())
      .filter(Boolean);

    const payload: {
      name: string;
      providerType: string;
      apiKey: string;
      apiBase: string;
      defaultModel: string;
      embeddingModel?: string;
      extraModels?: string[];
      extraParams?: Record<string, unknown>;
    } = { name, providerType, apiKey: apiKey || undefined!, apiBase, defaultModel };
    // Don't send empty apiKey on edit — keeps the existing key in DB
    if (!apiKey && isEditing) {
      delete (payload as Record<string, unknown>).apiKey;
    }
    if (embeddingModel) {
      payload.embeddingModel = embeddingModel;
    }
    if (parsedExtraModels.length > 0) {
      payload.extraModels = parsedExtraModels;
    }
    if (parsedExtra) {
      payload.extraParams = parsedExtra;
    }
    onSave(payload);
  };

  const isEditing = initial != null;
  return (
    <form
      onSubmit={handleSubmit}
      className="flex flex-col gap-3 rounded-lg border border-border bg-card p-4"
    >
      <h4 className="text-sm font-semibold text-foreground">
        {isEditing ? t("admin.editProvider") : t("admin.addProvider")}
      </h4>

      <div className="grid gap-3 sm:grid-cols-2">
        <div className="flex flex-col gap-1">
          <label className="text-xs text-muted-foreground">{t("admin.providerName")}</label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="openai-main"
            required
            className={INPUT_CLASS}
          />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs text-muted-foreground">{t("admin.providerType")}</label>
          <select
            value={providerType}
            onChange={(e) => setProviderType(e.target.value)}
            className={INPUT_CLASS}
          >
            <option value="openai">openai</option>
            <option value="anthropic">anthropic</option>
            <option value="custom">custom</option>
          </select>
        </div>
      </div>

      <div className="flex flex-col gap-1">
        <label className="text-xs text-muted-foreground">{t("admin.apiKey")}</label>
        <input
          type="password"
          value={apiKey}
          onChange={(e) => {
            setApiKey(e.target.value);
            setTested(false);
          }}
          placeholder={isEditing ? t("admin.apiKeyPlaceholder") : "sk-..."}
          required={!isEditing}
          className={INPUT_CLASS}
        />
      </div>

      <div className="flex flex-col gap-1">
        <label className="text-xs text-muted-foreground">{t("admin.apiBase")}</label>
        <input
          type="text"
          value={apiBase}
          onChange={(e) => {
            setApiBase(e.target.value);
            setTested(false);
          }}
          placeholder="https://api.openai.com/v1"
          required
          className={INPUT_CLASS}
        />
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <div className="flex flex-col gap-1">
          <label className="text-xs text-muted-foreground">{t("admin.defaultModel")}</label>
          <input
            type="text"
            value={defaultModel}
            onChange={(e) => {
              setDefaultModel(e.target.value);
              setTested(false);
            }}
            placeholder="gpt-4o-mini"
            required
            className={INPUT_CLASS}
          />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs text-muted-foreground">
            {t("admin.embeddingModel")}
          </label>
          <input
            type="text"
            value={embeddingModel}
            onChange={(e) => setEmbeddingModel(e.target.value)}
            placeholder="text-embedding-3-small"
            className={INPUT_CLASS}
          />
        </div>
      </div>

      {/* Additional available models */}
      <div className="flex flex-col gap-1">
        <label className="text-xs text-muted-foreground">
          {t("admin.availableModels", "其他可用模型")}
        </label>
        <input
          type="text"
          value={extraModelsStr}
          onChange={(e) => setExtraModelsStr(e.target.value)}
          placeholder="qwen3-32b, qwen3-8b, deepseek-v3"
          className={INPUT_CLASS}
        />
        <span className="text-xs text-muted-foreground">
          {t("admin.availableModelsHint", "逗号分隔。这些模型会出现在 Agent 配置的模型选择列表中。")}
        </span>
      </div>

      {/* Extra params */}
      <div className="flex flex-col gap-1">
        <label className="text-xs text-muted-foreground">
          {t("admin.extraParams")}
        </label>
        <textarea
          value={extraParamsStr}
          onChange={(e) => {
            setExtraParamsStr(e.target.value);
            setExtraParamsError("");
          }}
          placeholder={'{"chat_template_kwargs": {"enable_thinking": false}}'}
          rows={3}
          className={`rounded-md border bg-background px-3 py-2 font-mono text-xs text-foreground outline-none focus:border-primary ${
            extraParamsError ? "border-destructive" : "border-border"
          }`}
        />
        {extraParamsError && (
          <span className="text-xs text-destructive">{extraParamsError}</span>
        )}
        <span className="text-xs text-muted-foreground">
          {t("admin.extraParamsHint")}
        </span>
      </div>

      {/* Test result */}
      {testResult && (
        <div
          className={`rounded-md p-3 text-sm ${
            testResult.success
              ? "bg-green-50 text-green-700 dark:bg-green-900/20 dark:text-green-400"
              : "bg-red-50 text-red-700 dark:bg-red-900/20 dark:text-red-400"
          }`}
        >
          {testResult.success ? t("admin.testSuccess") : t("admin.testFailed")}
          {testResult.message ? ` — ${testResult.message}` : ""}
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => void handleTest()}
          disabled={isTesting || (!apiKey && !isEditing)}
          className="flex items-center gap-1.5 rounded-md border border-border px-3 py-2 text-sm font-medium text-foreground hover:bg-accent disabled:opacity-50"
        >
          {isTesting ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <FlaskConical className="h-4 w-4" />
          )}
          {isTesting ? t("admin.testing") : t("admin.testConnection")}
        </button>
        <button
          type="submit"
          disabled={isSaving || (!tested && !isEditing)}
          title={!tested && !isEditing ? t("admin.testRequired") : undefined}
          className="flex items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
        >
          {isSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : t("common.save")}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="rounded-md border border-border px-4 py-2 text-sm text-foreground hover:bg-accent"
        >
          {t("common.cancel")}
        </button>
      </div>
    </form>
  );
}

// ---------------------------------------------------------------------------
// LLM Providers Content (existing)
// ---------------------------------------------------------------------------
/** Convert form data (extraModels[]) to API data (purposeModels._extra). */
function mapFormToApi(data: {
  name: string;
  providerType: string;
  apiKey: string;
  apiBase: string;
  defaultModel: string;
  embeddingModel?: string;
  extraModels?: string[];
  extraParams?: Record<string, unknown>;
}) {
  const { extraModels, ...rest } = data;
  if (extraModels && extraModels.length > 0) {
    return { ...rest, purposeModels: { _extra: extraModels.join(", ") } };
  }
  return rest;
}

function LLMContent() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, { success: boolean; message: string }>>({});
  const [error, setError] = useState("");

  const { data: providers, isLoading } = useQuery({
    queryKey: ["admin", "llm-providers"],
    queryFn: getLLMProviders,
  });

  const createMutation = useMutation({
    mutationFn: createLLMProvider,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["admin", "llm-providers"] });
      setShowForm(false);
      setError("");
    },
    onError: (err) => setError(getErrorMessage(err)),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Parameters<typeof updateLLMProvider>[1] }) =>
      updateLLMProvider(id, data),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["admin", "llm-providers"] });
      setEditingId(null);
      setError("");
    },
    onError: (err) => setError(getErrorMessage(err)),
  });

  const deleteMutation = useMutation({
    mutationFn: deleteLLMProvider,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["admin", "llm-providers"] });
      setConfirmDeleteId(null);
    },
    onError: (err) => setError(getErrorMessage(err)),
  });

  const defaultMutation = useMutation({
    mutationFn: setDefaultProvider,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["admin", "llm-providers"] });
    },
    onError: (err) => setError(getErrorMessage(err)),
  });

  const handleTest = async (id: string) => {
    setTestingId(id);
    try {
      const result = await testLLMProvider(id);
      setTestResults((prev) => ({ ...prev, [id]: result }));
    } catch (err) {
      setTestResults((prev) => ({
        ...prev,
        [id]: { success: false, message: getErrorMessage(err) },
      }));
    } finally {
      setTestingId(null);
    }
  };

  const handleToggle = (provider: LLMProviderRaw) => {
    updateMutation.mutate({
      id: provider.id,
      data: { isEnabled: !provider.isEnabled },
    });
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold text-foreground">
          {t("admin.llmProviders")}
        </h3>
        {!showForm && editingId == null && (
          <button
            onClick={() => setShowForm(true)}
            className="flex items-center gap-1.5 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground"
          >
            <Plus className="h-4 w-4" />
            {t("admin.addProvider")}
          </button>
        )}
      </div>

      {error && (
        <div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
          {error}
        </div>
      )}

      {/* Create form */}
      {showForm && (
        <LLMProviderForm
          onSave={(data) => createMutation.mutate(mapFormToApi(data))}
          onCancel={() => {
            setShowForm(false);
            setError("");
          }}
          isSaving={createMutation.isPending}
        />
      )}

      {/* Empty state */}
      {!showForm && (providers == null || providers.length === 0) && (
        <div className="flex flex-col items-center gap-3 rounded-lg border-2 border-dashed border-border py-12">
          <Cpu className="h-10 w-10 text-muted-foreground" />
          <p className="text-sm font-medium text-muted-foreground">
            {t("admin.noProviders")}
          </p>
          <p className="text-xs text-muted-foreground">
            {t("admin.configureProvider")}
          </p>
        </div>
      )}

      {/* Provider cards */}
      {(providers ?? []).map((provider) => (
        <div key={provider.id}>
          {editingId === provider.id ? (
            <LLMProviderForm
              initial={provider}
              onSave={(data) =>
                updateMutation.mutate({ id: provider.id, data: mapFormToApi(data) })
              }
              onCancel={() => {
                setEditingId(null);
                setError("");
              }}
              isSaving={updateMutation.isPending}
            />
          ) : (
            <div className="rounded-lg border border-border bg-card p-4">
              {/* Header row */}
              <div className="mb-3 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Cpu className="h-4 w-4 text-muted-foreground" />
                  <span className="font-semibold text-foreground">{provider.name}</span>
                  {provider.isDefault && (
                    <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700 dark:bg-amber-900/30 dark:text-amber-400">
                      <Star className="h-3 w-3" />
                      {t("admin.default")}
                    </span>
                  )}
                  <StatusBadge status={provider.isEnabled ? "enabled" : "disabled"} />
                </div>
              </div>

              {/* Info grid */}
              <div className="mb-4 grid gap-x-6 gap-y-1.5 text-sm sm:grid-cols-2 lg:grid-cols-3">
                <div>
                  <span className="text-muted-foreground">{t("admin.providerType")}: </span>
                  <span className="text-foreground">{provider.providerType}</span>
                </div>
                <div>
                  <span className="text-muted-foreground">{t("admin.defaultModel")}: </span>
                  <span className="font-mono text-foreground">{provider.defaultModel}</span>
                </div>
                <div>
                  <span className="text-muted-foreground">{t("admin.apiBase")}: </span>
                  <span className="text-foreground">{provider.apiBase}</span>
                </div>
                <div>
                  <span className="text-muted-foreground">{t("admin.apiKey")}: </span>
                  <code className="rounded bg-muted px-1.5 py-0.5 text-xs">{provider.apiKeyMasked}</code>
                </div>
                {provider.embeddingModel && (
                  <div>
                    <span className="text-muted-foreground">{t("admin.embeddingModel")}: </span>
                    <span className="font-mono text-foreground">{provider.embeddingModel}</span>
                  </div>
                )}
                {provider.extraParams && Object.keys(provider.extraParams).length > 0 && (
                  <div className="sm:col-span-2 lg:col-span-3">
                    <span className="text-muted-foreground">{t("admin.extraParams")}: </span>
                    <code className="rounded bg-muted px-1.5 py-0.5 text-xs">
                      {JSON.stringify(provider.extraParams)}
                    </code>
                  </div>
                )}
              </div>

              {/* Test result inline */}
              {testResults[provider.id] != null && (
                <div
                  className={`mb-3 rounded-md p-2 text-xs ${
                    testResults[provider.id]!.success
                      ? "bg-green-50 text-green-700 dark:bg-green-900/20 dark:text-green-400"
                      : "bg-red-50 text-red-700 dark:bg-red-900/20 dark:text-red-400"
                  }`}
                >
                  {testResults[provider.id]!.success ? t("admin.testSuccess") : t("admin.testFailed")}
                  {testResults[provider.id]!.message ? ` — ${testResults[provider.id]!.message}` : ""}
                </div>
              )}

              {/* Actions */}
              <div className="flex flex-wrap items-center gap-2">
                <button
                  onClick={() => void handleTest(provider.id)}
                  disabled={testingId === provider.id}
                  className="flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1.5 text-xs font-medium text-foreground hover:bg-accent disabled:opacity-50"
                >
                  {testingId === provider.id ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <FlaskConical className="h-3.5 w-3.5" />
                  )}
                  {t("admin.testConnection")}
                </button>
                <button
                  onClick={() => setEditingId(provider.id)}
                  className="flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1.5 text-xs font-medium text-foreground hover:bg-accent"
                >
                  <Pencil className="h-3.5 w-3.5" />
                  {t("admin.editProvider")}
                </button>
                {!provider.isDefault && (
                  <button
                    onClick={() => defaultMutation.mutate(provider.id)}
                    disabled={defaultMutation.isPending}
                    className="flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1.5 text-xs font-medium text-foreground hover:bg-accent disabled:opacity-50"
                  >
                    <Star className="h-3.5 w-3.5" />
                    {t("admin.setDefault")}
                  </button>
                )}
                <button
                  onClick={() => handleToggle(provider)}
                  disabled={updateMutation.isPending}
                  className="flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1.5 text-xs font-medium text-foreground hover:bg-accent disabled:opacity-50"
                >
                  <Power className="h-3.5 w-3.5" />
                  {provider.isEnabled ? t("feeds.disable") : t("feeds.enable")}
                </button>
                {confirmDeleteId === provider.id ? (
                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => deleteMutation.mutate(provider.id)}
                      disabled={deleteMutation.isPending}
                      className="rounded px-2 py-1 text-xs font-medium text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20"
                    >
                      {t("common.confirm")}
                    </button>
                    <button
                      onClick={() => setConfirmDeleteId(null)}
                      className="rounded px-2 py-1 text-xs text-muted-foreground hover:bg-muted"
                    >
                      {t("common.cancel")}
                    </button>
                  </div>
                ) : (
                  <button
                    onClick={() => setConfirmDeleteId(provider.id)}
                    className="flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1.5 text-xs font-medium text-destructive hover:bg-destructive/10"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                    {t("common.delete")}
                  </button>
                )}
              </div>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Profile Form (create / edit)
// ---------------------------------------------------------------------------
function ProfileForm({
  initial,
  onSave,
  onCancel,
  isSaving,
}: {
  initial?: LLMProfileRaw;
  onSave: (data: {
    name: string;
    description?: string | undefined;
    temperature?: number | null | undefined;
    maxTokens?: number | null | undefined;
    topP?: number | null | undefined;
    thinkingEnabled?: boolean | null | undefined;
    thinkingBudgetTokens?: number | null | undefined;
    timeoutSeconds?: number | undefined;
    maxRetries?: number | undefined;
    extraParams?: Record<string, unknown> | undefined;
  }) => void;
  onCancel: () => void;
  isSaving: boolean;
}) {
  const { t } = useTranslation();
  const isEditing = initial != null;

  const [name, setName] = useState(initial?.name ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [temperature, setTemperature] = useState<string>(
    initial?.temperature != null ? String(initial.temperature) : "",
  );
  const [maxTokens, setMaxTokens] = useState<string>(
    initial?.maxTokens != null ? String(initial.maxTokens) : "",
  );
  const [topP, setTopP] = useState<string>(
    initial?.topP != null ? String(initial.topP) : "",
  );
  const [thinkingEnabled, setThinkingEnabled] = useState<string>(
    initial?.thinkingEnabled === true ? "true" : initial?.thinkingEnabled === false ? "false" : "",
  );
  const [thinkingBudgetTokens, setThinkingBudgetTokens] = useState<string>(
    initial?.thinkingBudgetTokens != null ? String(initial.thinkingBudgetTokens) : "",
  );
  const [timeoutSeconds, setTimeoutSeconds] = useState(initial?.timeoutSeconds?.toString() ?? "");
  const [maxRetries, setMaxRetries] = useState(initial?.maxRetries?.toString() ?? "");
  const [extraParamsStr, setExtraParamsStr] = useState(
    initial?.extraParams ? JSON.stringify(initial.extraParams, null, 2) : "",
  );
  const [extraParamsError, setExtraParamsError] = useState("");

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    let parsedExtra: Record<string, unknown> | undefined;
    if (extraParamsStr.trim()) {
      try {
        parsedExtra = JSON.parse(extraParamsStr.trim()) as Record<string, unknown>;
        setExtraParamsError("");
      } catch {
        setExtraParamsError(t("admin.invalidJson"));
        return;
      }
    }
    onSave({
      name,
      description: description || undefined,
      temperature: temperature !== "" ? Number(temperature) : null,
      maxTokens: maxTokens !== "" ? Number(maxTokens) : null,
      topP: topP !== "" ? Number(topP) : null,
      thinkingEnabled: thinkingEnabled === "true" ? true : thinkingEnabled === "false" ? false : null,
      thinkingBudgetTokens: thinkingBudgetTokens !== "" ? Number(thinkingBudgetTokens) : null,
      timeoutSeconds: timeoutSeconds ? parseInt(timeoutSeconds, 10) : undefined,
      maxRetries: maxRetries ? parseInt(maxRetries, 10) : undefined,
      extraParams: parsedExtra,
    });
  };

  return (
    <form
      onSubmit={handleSubmit}
      className="flex flex-col gap-3 rounded-lg border border-border bg-card p-4"
    >
      <h4 className="text-sm font-semibold text-foreground">
        {isEditing ? t("admin.editProfile") : t("admin.addProfile")}
      </h4>

      <div className="grid gap-3 sm:grid-cols-2">
        <div className="flex flex-col gap-1">
          <label className="text-xs text-muted-foreground">{t("admin.profileName")}</label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. creative, precise"
            required
            className={INPUT_CLASS}
          />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs text-muted-foreground">{t("admin.profileDescription")}</label>
          <input
            type="text"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder=""
            className={INPUT_CLASS}
          />
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        <div className="flex flex-col gap-1">
          <label className="text-xs text-muted-foreground">{t("admin.temperature")}</label>
          <input
            type="number"
            value={temperature}
            onChange={(e) => setTemperature(e.target.value)}
            step={0.1}
            min={0}
            max={2}
            placeholder="0.0 - 2.0"
            className={INPUT_CLASS}
          />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs text-muted-foreground">{t("admin.maxTokens")}</label>
          <input
            type="number"
            value={maxTokens}
            onChange={(e) => setMaxTokens(e.target.value)}
            min={1}
            placeholder="e.g. 4096"
            className={INPUT_CLASS}
          />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs text-muted-foreground">{t("admin.topP")}</label>
          <input
            type="number"
            value={topP}
            onChange={(e) => setTopP(e.target.value)}
            step={0.1}
            min={0}
            max={1}
            placeholder="0.0 - 1.0"
            className={INPUT_CLASS}
          />
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <div className="flex flex-col gap-1">
          <label className="text-xs text-muted-foreground">{t("admin.thinkingEnabled")}</label>
          <select
            value={thinkingEnabled}
            onChange={(e) => {
              setThinkingEnabled(e.target.value);
              if (e.target.value !== "true") {
                setThinkingBudgetTokens("");
              }
            }}
            className={INPUT_CLASS}
          >
            <option value="">{t("admin.thinkingDefault")}</option>
            <option value="true">{t("admin.thinkingOn")}</option>
            <option value="false">{t("admin.thinkingOff")}</option>
          </select>
        </div>
        {thinkingEnabled === "true" && (
          <div className="flex flex-col gap-1">
            <label className="text-xs text-muted-foreground">{t("admin.thinkingBudgetTokens")}</label>
            <input
              type="number"
              value={thinkingBudgetTokens}
              onChange={(e) => setThinkingBudgetTokens(e.target.value)}
              min={1}
              placeholder="e.g. 10000"
              className={INPUT_CLASS}
            />
          </div>
        )}
      </div>

      {/* Timeout & Retry */}
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="flex flex-col gap-1">
          <label className="text-xs text-muted-foreground">{t("admin.timeoutSeconds")}</label>
          <input
            type="number"
            value={timeoutSeconds}
            onChange={(e) => setTimeoutSeconds(e.target.value)}
            min={1}
            placeholder="120"
            className={INPUT_CLASS}
          />
          <span className="text-xs text-muted-foreground">{t("admin.timeoutHint")}</span>
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs text-muted-foreground">{t("admin.maxRetries")}</label>
          <input
            type="number"
            value={maxRetries}
            onChange={(e) => setMaxRetries(e.target.value)}
            min={0}
            max={10}
            placeholder="0"
            className={INPUT_CLASS}
          />
          <span className="text-xs text-muted-foreground">{t("admin.maxRetriesHint")}</span>
        </div>
      </div>

      <div className="flex flex-col gap-1">
        <label className="text-xs text-muted-foreground">{t("admin.extraParams")}</label>
        <textarea
          value={extraParamsStr}
          onChange={(e) => {
            setExtraParamsStr(e.target.value);
            setExtraParamsError("");
          }}
          placeholder="{}"
          rows={3}
          className={`rounded-md border bg-background px-3 py-2 font-mono text-xs text-foreground outline-none focus:border-primary ${
            extraParamsError ? "border-destructive" : "border-border"
          }`}
        />
        {extraParamsError && (
          <span className="text-xs text-destructive">{extraParamsError}</span>
        )}
      </div>

      <div className="flex flex-wrap gap-2">
        <button
          type="submit"
          disabled={isSaving}
          className="flex items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
        >
          {isSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : t("common.save")}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="rounded-md border border-border px-4 py-2 text-sm text-foreground hover:bg-accent"
        >
          {t("common.cancel")}
        </button>
      </div>
    </form>
  );
}

// ---------------------------------------------------------------------------
// Profiles Content
// ---------------------------------------------------------------------------
function ProfilesContent() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [error, setError] = useState("");

  const { data: profiles, isLoading } = useQuery({
    queryKey: ["admin", "llm-profiles"],
    queryFn: getLLMProfiles,
  });

  const createMutation = useMutation({
    mutationFn: createLLMProfile,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["admin", "llm-profiles"] });
      setShowForm(false);
      setError("");
    },
    onError: (err) => setError(getErrorMessage(err)),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Parameters<typeof updateLLMProfile>[1] }) =>
      updateLLMProfile(id, data),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["admin", "llm-profiles"] });
      setEditingId(null);
      setError("");
    },
    onError: (err) => setError(getErrorMessage(err)),
  });

  const deleteMutation = useMutation({
    mutationFn: deleteLLMProfile,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["admin", "llm-profiles"] });
      setConfirmDeleteId(null);
    },
    onError: (err) => setError(getErrorMessage(err)),
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold text-foreground">
          {t("admin.profiles")}
        </h3>
        {!showForm && editingId == null && (
          <button
            onClick={() => setShowForm(true)}
            className="flex items-center gap-1.5 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground"
          >
            <Plus className="h-4 w-4" />
            {t("admin.addProfile")}
          </button>
        )}
      </div>

      {error && (
        <div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
          {error}
        </div>
      )}

      {/* Create form */}
      {showForm && (
        <ProfileForm
          onSave={(data) => createMutation.mutate(data)}
          onCancel={() => {
            setShowForm(false);
            setError("");
          }}
          isSaving={createMutation.isPending}
        />
      )}

      {/* Empty state */}
      {!showForm && (profiles == null || profiles.length === 0) && (
        <div className="flex flex-col items-center gap-3 rounded-lg border-2 border-dashed border-border py-12">
          <Sliders className="h-10 w-10 text-muted-foreground" />
          <p className="text-sm font-medium text-muted-foreground">
            {t("admin.noProfiles")}
          </p>
          <p className="text-xs text-muted-foreground">
            {t("admin.createProfileHint")}
          </p>
        </div>
      )}

      {/* Profile cards */}
      {(profiles ?? []).map((profile) => (
        <div key={profile.id}>
          {editingId === profile.id ? (
            <ProfileForm
              initial={profile}
              onSave={(data) => updateMutation.mutate({ id: profile.id, data })}
              onCancel={() => {
                setEditingId(null);
                setError("");
              }}
              isSaving={updateMutation.isPending}
            />
          ) : (
            <div className="rounded-lg border border-border bg-card p-4">
              <div className="mb-2 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Sliders className="h-4 w-4 text-muted-foreground" />
                  <span className="font-semibold text-foreground">{profile.name}</span>
                  {profile.description && (
                    <span className="text-sm text-muted-foreground">
                      {profile.description}
                    </span>
                  )}
                </div>
              </div>

              {/* Parameter badges */}
              <div className="mb-3 flex flex-wrap gap-1.5">
                {profile.temperature != null && (
                  <span className="rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-700 dark:bg-blue-900/30 dark:text-blue-400">
                    temp: {profile.temperature}
                  </span>
                )}
                {profile.maxTokens != null && (
                  <span className="rounded-full bg-purple-100 px-2 py-0.5 text-xs font-medium text-purple-700 dark:bg-purple-900/30 dark:text-purple-400">
                    max_tokens: {profile.maxTokens}
                  </span>
                )}
                {profile.topP != null && (
                  <span className="rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700 dark:bg-green-900/30 dark:text-green-400">
                    top_p: {profile.topP}
                  </span>
                )}
                {profile.thinkingEnabled != null && (
                  <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700 dark:bg-amber-900/30 dark:text-amber-400">
                    thinking: {profile.thinkingEnabled ? t("admin.thinkingOn") : t("admin.thinkingOff")}
                  </span>
                )}
                {profile.thinkingBudgetTokens != null && (
                  <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700 dark:bg-amber-900/30 dark:text-amber-400">
                    thinking_budget: {profile.thinkingBudgetTokens}
                  </span>
                )}
                {profile.timeoutSeconds != null && (
                  <span className="rounded-full bg-orange-100 px-2 py-0.5 text-xs font-medium text-orange-700 dark:bg-orange-900/30 dark:text-orange-400">
                    timeout: {profile.timeoutSeconds}s
                  </span>
                )}
                {profile.maxRetries != null && (
                  <span className="rounded-full bg-orange-100 px-2 py-0.5 text-xs font-medium text-orange-700 dark:bg-orange-900/30 dark:text-orange-400">
                    retries: {profile.maxRetries}
                  </span>
                )}
                {profile.extraParams != null && Object.keys(profile.extraParams).length > 0 && (
                  <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-700 dark:bg-gray-900/30 dark:text-gray-400">
                    extra_params: {JSON.stringify(profile.extraParams)}
                  </span>
                )}
              </div>

              {/* Actions */}
              <div className="flex flex-wrap items-center gap-2">
                <button
                  onClick={() => setEditingId(profile.id)}
                  className="flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1.5 text-xs font-medium text-foreground hover:bg-accent"
                >
                  <Pencil className="h-3.5 w-3.5" />
                  {t("admin.editProfile")}
                </button>
                {confirmDeleteId === profile.id ? (
                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => deleteMutation.mutate(profile.id)}
                      disabled={deleteMutation.isPending}
                      className="rounded px-2 py-1 text-xs font-medium text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20"
                    >
                      {t("common.confirm")}
                    </button>
                    <button
                      onClick={() => setConfirmDeleteId(null)}
                      className="rounded px-2 py-1 text-xs text-muted-foreground hover:bg-muted"
                    >
                      {t("common.cancel")}
                    </button>
                  </div>
                ) : (
                  <button
                    onClick={() => setConfirmDeleteId(profile.id)}
                    className="flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1.5 text-xs font-medium text-destructive hover:bg-destructive/10"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                    {t("common.delete")}
                  </button>
                )}
              </div>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Agent State type for lifted state
// ---------------------------------------------------------------------------
interface AgentState {
  providerId: string;
  model: string;
  profileId: string;
}

// ---------------------------------------------------------------------------
// Agent Config Row (controlled component)
// ---------------------------------------------------------------------------
function AgentConfigRow({
  agentId,
  state,
  originalState,
  providers,
  profiles,
  availableModels,
  onChange,
  onReset,
  isDeleting,
  tier,
  tierLocked,
  tierLockedReason,
  onTierToggle,
}: {
  agentId: string;
  state: AgentState;
  originalState: AgentState;
  providers: LLMProviderRaw[];
  profiles: LLMProfileRaw[];
  availableModels: string[];
  onChange: (newState: AgentState) => void;
  onReset: () => void;
  isDeleting: boolean;
  tier?: "p1" | "p2" | undefined;
  tierLocked?: boolean | undefined;
  tierLockedReason?: string | undefined;
  onTierToggle?: (() => void) | undefined;
}) {
  const { t } = useTranslation();

  const isDirty =
    state.providerId !== originalState.providerId ||
    state.model !== originalState.model ||
    state.profileId !== originalState.profileId;
  const hasServerConfig =
    originalState.providerId !== "" ||
    originalState.model !== "" ||
    originalState.profileId !== "";

  return (
    <tr className="border-b border-border last:border-b-0">
      <td className="px-3 py-2.5 text-sm font-medium text-foreground">
        <div className="flex items-center gap-1.5">
          <Bot className="h-3.5 w-3.5 text-muted-foreground" />
          {agentId}
          {isDirty && <span className="text-yellow-500">*</span>}
        </div>
      </td>
      <td className="px-3 py-2.5">
        {tier != null && onTierToggle != null ? (
          <button
            onClick={onTierToggle}
            disabled={tierLocked}
            title={tierLocked ? tierLockedReason : undefined}
            className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium transition-colors ${
              tierLocked ? "cursor-not-allowed opacity-60" : "cursor-pointer"
            } ${
              tier === "p1"
                ? "bg-blue-100 text-blue-700 hover:bg-blue-200 dark:bg-blue-900/30 dark:text-blue-400 dark:hover:bg-blue-900/50"
                : "bg-gray-100 text-gray-600 hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-400 dark:hover:bg-gray-700"
            }`}
          >
            <Layers className="h-3 w-3" />
            {tier === "p1"
              ? t("admin.tierP1", "P1 高优先级")
              : t("admin.tierP2", "P2 分析")}
          </button>
        ) : (
          <span className="text-xs text-muted-foreground">-</span>
        )}
      </td>
      <td className="px-3 py-2.5">
        <select
          value={state.providerId}
          onChange={(e) => onChange({ ...state, providerId: e.target.value })}
          className={INPUT_CLASS + " w-full text-xs"}
        >
          <option value="">{t("admin.default")}</option>
          {providers.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
      </td>
      <td className="px-3 py-2.5">
        <input
          list={`models-${agentId}`}
          value={state.model}
          onChange={(e) => onChange({ ...state, model: e.target.value })}
          placeholder={t("admin.default")}
          className={INPUT_CLASS + " w-full text-xs"}
        />
        <datalist id={`models-${agentId}`}>
          {availableModels.map((m) => (
            <option key={m} value={m} />
          ))}
        </datalist>
      </td>
      <td className="px-3 py-2.5">
        <select
          value={state.profileId}
          onChange={(e) => onChange({ ...state, profileId: e.target.value })}
          className={INPUT_CLASS + " w-full text-xs"}
        >
          <option value="">{t("admin.default")}</option>
          {profiles.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
      </td>
      <td className="px-3 py-2.5">
        <div className="flex items-center gap-1.5">
          {hasServerConfig && (
            <button
              onClick={onReset}
              disabled={isDeleting}
              className="flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs font-medium text-foreground hover:bg-accent disabled:opacity-50"
            >
              {isDeleting ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <RotateCcw className="h-3 w-3" />
              )}
              {t("admin.resetConfig")}
            </button>
          )}
        </div>
      </td>
    </tr>
  );
}

// ---------------------------------------------------------------------------
// Agent Config Content (with lifted state + save-all)
// ---------------------------------------------------------------------------
function AgentConfigContent() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  const { data: agentData, isLoading: agentLoading } = useQuery({
    queryKey: ["admin", "agent-configs"],
    queryFn: getAgentConfigs,
  });

  const { data: providers, isLoading: providersLoading } = useQuery({
    queryKey: ["admin", "llm-providers"],
    queryFn: getLLMProviders,
  });

  const { data: profiles, isLoading: profilesLoading } = useQuery({
    queryKey: ["admin", "llm-profiles"],
    queryFn: getLLMProfiles,
  });

  const { data: priorityData, isLoading: priorityLoading } = useQuery({
    queryKey: ["admin", "agent-priority"],
    queryFn: getAgentPriority,
  });

  const isLoading = agentLoading || providersLoading || profilesLoading || priorityLoading;

  // Lifted state
  const [agentStates, setAgentStates] = useState<Record<string, AgentState>>({});
  const [originalStates, setOriginalStates] = useState<Record<string, AgentState>>({});
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [deletingAgent, setDeletingAgent] = useState<string | null>(null);
  const [error, setError] = useState("");

  // Priority tier state
  const [p2Enabled, setP2Enabled] = useState(false);
  const [originalP2Enabled, setOriginalP2Enabled] = useState(false);
  const [tierOverrides, setTierOverrides] = useState<Record<string, "p1" | "p2">>({});
  const [originalTiers, setOriginalTiers] = useState<Record<string, "p1" | "p2">>({});

  // Initialize / sync from fetched data
  useEffect(() => {
    if (agentData) {
      const states: Record<string, AgentState> = {};
      for (const agentId of agentData.registeredAgents) {
        const config = agentData.configs.find((c) => c.agentId === agentId);
        states[agentId] = {
          providerId: config?.providerId ?? "",
          model: config?.model ?? "",
          profileId: config?.profileId ?? "",
        };
      }
      setAgentStates(states);
      setOriginalStates(states);
    }
  }, [agentData]);

  // Initialize priority data
  useEffect(() => {
    if (priorityData) {
      setP2Enabled(priorityData.p2Enabled);
      setOriginalP2Enabled(priorityData.p2Enabled);
      const tiers: Record<string, "p1" | "p2"> = {};
      for (const agent of priorityData.agents) {
        tiers[agent.agentId] = agent.tier;
      }
      setTierOverrides(tiers);
      setOriginalTiers(tiers);
    }
  }, [priorityData]);

  // Build a map of agents that require P2 agents (locked as P2)
  const lockedP2Agents = useMemo(() => {
    if (!priorityData) return new Set<string>();
    const locked = new Set<string>();
    for (const agent of priorityData.agents) {
      if (agent.requires.length > 0) {
        // If this agent requires another agent that is P2, it may be locked
        // Actually: agents with `requires` containing P2 agents are themselves locked as P2
        const hasP2Dependency = agent.requires.some((dep) => {
          const depTier = tierOverrides[dep];
          return depTier === "p2";
        });
        if (hasP2Dependency) {
          locked.add(agent.agentId);
        }
      }
    }
    return locked;
  }, [priorityData, tierOverrides]);

  // Extract unique model names from all providers (including purposeModels)
  const availableModels = useMemo(() => {
    if (!providers) return [];
    const modelSet = new Set<string>();
    for (const p of providers) {
      if (p.defaultModel) modelSet.add(p.defaultModel);
      if (p.embeddingModel) modelSet.add(p.embeddingModel);
      if (p.purposeModels) {
        for (const [key, val] of Object.entries(p.purposeModels)) {
          if (!val) continue;
          if (key === "_extra") {
            // Comma-separated list of additional available models
            for (const m of val.split(/[,，]/)) {
              const trimmed = m.trim();
              if (trimmed) modelSet.add(trimmed);
            }
          } else {
            modelSet.add(val);
          }
        }
      }
    }
    return Array.from(modelSet).sort();
  }, [providers]);

  const isConfigDirty = useCallback(
    (agentId: string) => {
      const current = agentStates[agentId];
      const original = originalStates[agentId];
      if (!current || !original) return false;
      return (
        current.providerId !== original.providerId ||
        current.model !== original.model ||
        current.profileId !== original.profileId
      );
    },
    [agentStates, originalStates],
  );

  const isTierDirty = useMemo(() => {
    if (p2Enabled !== originalP2Enabled) return true;
    for (const agentId of Object.keys(tierOverrides)) {
      if (tierOverrides[agentId] !== originalTiers[agentId]) return true;
    }
    return false;
  }, [p2Enabled, originalP2Enabled, tierOverrides, originalTiers]);

  const configDirtyCount = useMemo(
    () => Object.keys(agentStates).filter(isConfigDirty).length,
    [agentStates, isConfigDirty],
  );

  const dirtyCount = configDirtyCount + (isTierDirty ? 1 : 0);

  const handleChange = useCallback((agentId: string, newState: AgentState) => {
    setAgentStates((prev) => ({ ...prev, [agentId]: newState }));
    setSaved(false);
  }, []);

  const handleTierToggle = useCallback((agentId: string) => {
    setTierOverrides((prev) => ({
      ...prev,
      [agentId]: prev[agentId] === "p1" ? "p2" : "p1",
    }));
    setSaved(false);
  }, []);

  const handleReset = useCallback(
    async (agentId: string) => {
      const original = originalStates[agentId];
      const hasServerConfig =
        original && (original.providerId !== "" || original.model !== "" || original.profileId !== "");
      if (hasServerConfig) {
        // Delete config from server
        setDeletingAgent(agentId);
        try {
          await deleteAgentConfig(agentId);
          void queryClient.invalidateQueries({ queryKey: ["admin", "agent-configs"] });
        } catch (err) {
          setError(getErrorMessage(err));
        } finally {
          setDeletingAgent(null);
        }
      } else {
        // Just revert local state
        setAgentStates((prev) => ({ ...prev, [agentId]: originalStates[agentId]! }));
      }
    },
    [originalStates, queryClient],
  );

  const handleSaveAll = async () => {
    setSaving(true);
    setError("");
    try {
      // Save agent config changes
      const dirtyAgents = Object.keys(agentStates).filter(isConfigDirty);
      for (const agentId of dirtyAgents) {
        const state = agentStates[agentId]!;
        await upsertAgentConfig(agentId, {
          providerId: state.providerId || null,
          model: state.model || null,
          profileId: state.profileId || null,
        });
      }

      // Save priority tier changes
      if (isTierDirty) {
        const p1Agents = Object.entries(tierOverrides)
          .filter(([, tier]) => tier === "p1")
          .map(([agentId]) => agentId);
        await updateAgentPriority({
          p2Enabled,
          p1Agents,
        });
        void queryClient.invalidateQueries({ queryKey: ["admin", "agent-priority"] });
      }

      void queryClient.invalidateQueries({ queryKey: ["admin", "agent-configs"] });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const allAgents = agentData?.registeredAgents ?? [];
  const priorityAgentMap = new Map(
    (priorityData?.agents ?? []).map((a) => [a.agentId, a]),
  );

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h3 className="text-lg font-semibold text-foreground">
          {t("admin.agentConfig")}
        </h3>
        <p className="mt-1 text-sm text-muted-foreground">
          {t("admin.agentConfigHint")}
        </p>
      </div>

      {/* P2 Enabled Toggle */}
      {priorityData && (
        <div className="flex items-center gap-3 rounded-lg border border-border bg-card p-4">
          <div className="flex flex-1 flex-col gap-0.5">
            <div className="flex items-center gap-2">
              <Layers className="h-4 w-4 text-muted-foreground" />
              <span className="text-sm font-medium text-foreground">
                {t("admin.p2Enabled", "分析类 Agent (P2)")}
              </span>
              {p2Enabled !== originalP2Enabled && (
                <span className="text-yellow-500 text-xs">*</span>
              )}
            </div>
            <p className="text-xs text-muted-foreground">
              {t(
                "admin.p2EnabledHint",
                "启用后，P2 级别的 Agent 将在 Pipeline 中执行深度分析。关闭则仅运行 P1 高优先级 Agent。",
              )}
            </p>
          </div>
          <button
            onClick={() => {
              setP2Enabled((prev) => !prev);
              setSaved(false);
            }}
            className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer items-center rounded-full transition-colors ${
              p2Enabled
                ? "bg-blue-600"
                : "bg-gray-300 dark:bg-gray-600"
            }`}
            role="switch"
            aria-checked={p2Enabled}
          >
            <span
              className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${
                p2Enabled ? "translate-x-6" : "translate-x-1"
              }`}
            />
          </button>
        </div>
      )}

      {error && (
        <div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
          {error}
        </div>
      )}

      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full">
          <thead>
            <tr className="border-b border-border bg-muted/50">
              <th className="px-3 py-2 text-left text-xs font-medium text-muted-foreground">
                {t("admin.agentId")}
              </th>
              <th className="px-3 py-2 text-left text-xs font-medium text-muted-foreground">
                {t("admin.tier", "Tier")}
              </th>
              <th className="px-3 py-2 text-left text-xs font-medium text-muted-foreground">
                {t("admin.provider")}
              </th>
              <th className="px-3 py-2 text-left text-xs font-medium text-muted-foreground">
                {t("admin.model")}
              </th>
              <th className="px-3 py-2 text-left text-xs font-medium text-muted-foreground">
                {t("admin.profile")}
              </th>
              <th className="px-3 py-2 text-left text-xs font-medium text-muted-foreground" />
            </tr>
          </thead>
          <tbody>
            {allAgents.map((agentId) => {
              const state = agentStates[agentId];
              const original = originalStates[agentId];
              if (!state || !original) return null;
              const priorityAgent = priorityAgentMap.get(agentId);
              const currentTier = tierOverrides[agentId];
              const isLocked = lockedP2Agents.has(agentId);
              const lockReason = isLocked
                ? t(
                    "admin.tierLocked",
                    "该 Agent 依赖 P2 级别 Agent，无法切换为 P1",
                  )
                : undefined;
              return (
                <AgentConfigRow
                  key={agentId}
                  agentId={agentId}
                  state={state}
                  originalState={original}
                  providers={providers ?? []}
                  profiles={profiles ?? []}
                  availableModels={availableModels}
                  onChange={(newState) => handleChange(agentId, newState)}
                  onReset={() => void handleReset(agentId)}
                  isDeleting={deletingAgent === agentId}
                  tier={priorityAgent ? currentTier : undefined}
                  tierLocked={isLocked}
                  tierLockedReason={lockReason}
                  onTierToggle={
                    priorityAgent ? () => handleTierToggle(agentId) : undefined
                  }
                />
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Save All button */}
      <div className="flex items-center justify-end gap-3">
        {dirtyCount > 0 && (
          <span className="text-sm text-muted-foreground">
            {dirtyCount} {dirtyCount === 1 ? "change" : "changes"}
          </span>
        )}
        <button
          onClick={() => void handleSaveAll()}
          disabled={dirtyCount === 0 || saving}
          className="flex items-center gap-1.5 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-blue-700 disabled:opacity-50 disabled:hover:bg-blue-600"
        >
          {saving ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : saved ? (
            <Check className="h-4 w-4" />
          ) : (
            <Save className="h-4 w-4" />
          )}
          {saved ? t("admin.configSaved") : t("admin.saveAll")}
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Page with Tabs
// ---------------------------------------------------------------------------
type TabKey = "providers" | "profiles" | "agents";

const TABS: { key: TabKey; labelKey: string; icon: typeof Cpu }[] = [
  { key: "providers", labelKey: "admin.llmProviders", icon: Cpu },
  { key: "profiles", labelKey: "admin.profiles", icon: Sliders },
  { key: "agents", labelKey: "admin.agentConfig", icon: Settings2 },
];

export default function AdminLLMPage() {
  const { t } = useTranslation();
  const [activeTab, setActiveTab] = useState<TabKey>("providers");

  return (
    <AdminLayout>
      {/* Tab bar */}
      <div className="mb-6 flex gap-1.5">
        {TABS.map(({ key, labelKey, icon: Icon }) => (
          <button
            key={key}
            onClick={() => setActiveTab(key)}
            className={`flex items-center gap-1.5 rounded-full px-4 py-1.5 text-sm font-medium transition-colors ${
              activeTab === key
                ? "bg-primary text-primary-foreground"
                : "bg-muted text-muted-foreground hover:bg-accent hover:text-foreground"
            }`}
          >
            <Icon className="h-4 w-4" />
            {t(labelKey)}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {activeTab === "providers" && <LLMContent />}
      {activeTab === "profiles" && <ProfilesContent />}
      {activeTab === "agents" && <AgentConfigContent />}
    </AdminLayout>
  );
}
