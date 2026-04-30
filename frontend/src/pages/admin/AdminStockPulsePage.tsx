import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Loader2,
  Save,
  RefreshCw,
  PlugZap,
  CheckCircle2,
  XCircle,
  Eye,
  EyeOff,
} from "lucide-react";
import {
  getStockPulseConfig,
  updateStockPulseConfig,
  testStockPulseConnection,
  getStockPulseWatched,
  triggerStockPulsePoll,
  type StockPulseTestResultRaw,
} from "@/api/admin";
import { getErrorMessage } from "@/api/client";
import { AdminLayout } from "@/components/admin/AdminLayout";
import { StatusBadge } from "@/components/admin/StatusBadge";
import { toast } from "@/stores/toastStore";

export default function AdminStockPulsePage() {
  const { t } = useTranslation();
  const qc = useQueryClient();

  const configQuery = useQuery({
    queryKey: ["admin", "stockpulse", "config"],
    queryFn: getStockPulseConfig,
  });

  const watchedQuery = useQuery({
    queryKey: ["admin", "stockpulse", "watched"],
    queryFn: () => getStockPulseWatched(200),
    refetchInterval: 30_000,
  });

  const [urlInput, setUrlInput] = useState("");
  const [apiKeyInput, setApiKeyInput] = useState("");
  const [showApiKey, setShowApiKey] = useState(false);
  const [testResult, setTestResult] = useState<StockPulseTestResultRaw | null>(null);

  // When the config first loads, seed the URL into the input. We don't
  // seed apiKey — the server only returns a masked preview, never raw.
  if (configQuery.data && urlInput === "" && configQuery.data.url) {
    setUrlInput(configQuery.data.url);
  }

  const saveMutation = useMutation({
    mutationFn: () =>
      updateStockPulseConfig({
        url: urlInput,
        // Empty string = clear; null/undefined = leave unchanged.
        apiKey: apiKeyInput === "" ? null : apiKeyInput,
      }),
    onSuccess: () => {
      toast({ variant: "success", title: t("admin.stockpulse.saved") });
      setApiKeyInput("");
      void qc.invalidateQueries({ queryKey: ["admin", "stockpulse", "config"] });
    },
    onError: (err) =>
      toast({
        variant: "error",
        title: t("admin.stockpulse.saveFailed"),
        description: getErrorMessage(err),
      }),
  });

  const testMutation = useMutation({
    mutationFn: testStockPulseConnection,
    onSuccess: (data) => {
      setTestResult(data);
      if (data.ok) {
        toast({
          variant: "success",
          title: t("admin.stockpulse.testOk"),
          description: data.message,
        });
      } else {
        toast({
          variant: "error",
          title: t("admin.stockpulse.testFailed"),
          description: data.message,
        });
      }
    },
    onError: (err) => {
      const msg = getErrorMessage(err);
      setTestResult({ ok: false, statusCode: null, message: msg, elapsedMs: null });
      toast({ variant: "error", title: t("admin.stockpulse.testFailed"), description: msg });
    },
  });

  const pollMutation = useMutation({
    mutationFn: (tier: "hot" | "warm" | "cold") => triggerStockPulsePoll(tier),
    onSuccess: (data) => {
      toast({
        variant: "success",
        title: t("admin.stockpulse.pollDispatched"),
        description: data.message,
      });
      // Refresh the watched table after a short delay so last_polled_at updates show up.
      setTimeout(() => {
        void qc.invalidateQueries({ queryKey: ["admin", "stockpulse", "watched"] });
      }, 3000);
    },
    onError: (err) =>
      toast({
        variant: "error",
        title: t("admin.stockpulse.pollFailed"),
        description: getErrorMessage(err),
      }),
  });

  const onSubmitConfig = (e: FormEvent) => {
    e.preventDefault();
    saveMutation.mutate();
  };

  const config = configQuery.data;
  const watched = watchedQuery.data;

  return (
    <AdminLayout>
      <div className="space-y-6">
        {/* Header */}
        <div>
          <h2 className="text-xl font-semibold text-foreground">
            {t("admin.stockpulse.title")}
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            {t("admin.stockpulse.description")}
          </p>
        </div>

        {/* Status snapshot */}
        {configQuery.isLoading ? (
          <div className="flex items-center gap-2 text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            {t("common.loading")}
          </div>
        ) : config ? (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <StatCard
              label={t("admin.stockpulse.status")}
              value={
                config.apiKeySet && config.url ? (
                  <StatusBadge status="active" />
                ) : (
                  <StatusBadge status="disabled" />
                )
              }
            />
            <StatCard
              label={t("admin.stockpulse.yamlEnabled")}
              value={
                <StatusBadge
                  status={config.enabledInYaml ? "enabled" : "disabled"}
                />
              }
            />
            <StatCard
              label={t("admin.stockpulse.pollInterval")}
              value={
                <span className="text-sm font-medium text-foreground">
                  {config.pollIntervalMinutes} {t("admin.stockpulse.minutes")}
                </span>
              }
            />
            <StatCard
              label={t("admin.stockpulse.defaultLimit")}
              value={
                <span className="text-sm font-medium text-foreground">
                  {config.defaultLimit}
                </span>
              }
            />
          </div>
        ) : null}

        {/* Config form */}
        <form
          onSubmit={onSubmitConfig}
          className="space-y-4 rounded-lg border border-border bg-card p-4"
        >
          <h3 className="text-sm font-semibold text-foreground">
            {t("admin.stockpulse.configHeading")}
          </h3>

          <div className="space-y-1.5">
            <label className="text-xs font-medium text-foreground" htmlFor="sp-url">
              {t("admin.stockpulse.urlLabel")}
            </label>
            <input
              id="sp-url"
              type="url"
              value={urlInput}
              onChange={(e) => setUrlInput(e.target.value)}
              placeholder="http://stockpulse-app:80"
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary"
            />
            <p className="text-xs text-muted-foreground">
              {t("admin.stockpulse.urlHint")}
            </p>
          </div>

          <div className="space-y-1.5">
            <label className="text-xs font-medium text-foreground" htmlFor="sp-key">
              {t("admin.stockpulse.apiKeyLabel")}
            </label>
            <div className="flex gap-2">
              <input
                id="sp-key"
                type={showApiKey ? "text" : "password"}
                value={apiKeyInput}
                onChange={(e) => setApiKeyInput(e.target.value)}
                placeholder={
                  config?.apiKeySet
                    ? `${t("admin.stockpulse.apiKeyCurrent")}: ${config.apiKeyPreview ?? ""}`
                    : t("admin.stockpulse.apiKeyPlaceholder")
                }
                className="flex-1 rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary"
                autoComplete="off"
              />
              <button
                type="button"
                onClick={() => setShowApiKey((v) => !v)}
                className="inline-flex items-center justify-center rounded-md border border-input bg-background px-2 text-muted-foreground hover:bg-muted"
                aria-label={showApiKey ? "Hide" : "Show"}
              >
                {showApiKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>
            <p className="text-xs text-muted-foreground">
              {t("admin.stockpulse.apiKeyHint")}
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2 pt-2">
            <button
              type="submit"
              disabled={saveMutation.isPending}
              className="inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-60"
            >
              {saveMutation.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Save className="h-4 w-4" />
              )}
              {t("admin.stockpulse.save")}
            </button>
            <button
              type="button"
              onClick={() => testMutation.mutate()}
              disabled={testMutation.isPending}
              className="inline-flex items-center gap-2 rounded-md border border-input bg-background px-4 py-2 text-sm font-medium text-foreground hover:bg-muted disabled:opacity-60"
            >
              {testMutation.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <PlugZap className="h-4 w-4" />
              )}
              {t("admin.stockpulse.testConnection")}
            </button>
            {testResult ? (
              <span
                className={`inline-flex items-center gap-1.5 text-xs ${
                  testResult.ok ? "text-green-600 dark:text-green-400" : "text-red-600 dark:text-red-400"
                }`}
              >
                {testResult.ok ? (
                  <CheckCircle2 className="h-3.5 w-3.5" />
                ) : (
                  <XCircle className="h-3.5 w-3.5" />
                )}
                {testResult.message}
                {testResult.elapsedMs != null && ` (${testResult.elapsedMs}ms)`}
              </span>
            ) : null}
          </div>
        </form>

        {/* Watched symbols */}
        <section className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-baseline gap-3">
              <h3 className="text-sm font-semibold text-foreground">
                {t("admin.stockpulse.watchedHeading")}
              </h3>
              {watched ? (
                <span className="text-xs text-muted-foreground">
                  {t("admin.stockpulse.watchedCount", { count: watched.total })}
                </span>
              ) : null}
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => pollMutation.mutate("hot")}
                disabled={pollMutation.isPending}
                className="inline-flex items-center gap-1.5 rounded-md border border-input bg-background px-2.5 py-1 text-xs text-muted-foreground hover:bg-muted disabled:opacity-60"
              >
                {pollMutation.isPending ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <RefreshCw className="h-3.5 w-3.5" />
                )}
                {t("admin.stockpulse.pollNow")}
              </button>
              <button
                type="button"
                onClick={() => watchedQuery.refetch()}
                className="inline-flex items-center gap-1.5 rounded-md border border-input bg-background px-2.5 py-1 text-xs text-muted-foreground hover:bg-muted"
              >
                <RefreshCw className={`h-3.5 w-3.5 ${watchedQuery.isFetching ? "animate-spin" : ""}`} />
                {t("common.refresh")}
              </button>
            </div>
          </div>

          <div className="overflow-hidden rounded-lg border border-border bg-card">
            <table className="min-w-full divide-y divide-border">
              <thead className="bg-muted/50">
                <tr>
                  <Th>{t("admin.stockpulse.colSymbol")}</Th>
                  <Th>{t("admin.stockpulse.colMarket")}</Th>
                  <Th>{t("admin.stockpulse.colRegisteredBy")}</Th>
                  <Th>{t("admin.stockpulse.colLastViewed")}</Th>
                  <Th>{t("admin.stockpulse.colLastPolled")}</Th>
                  <Th>{t("admin.stockpulse.colError")}</Th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border bg-background">
                {watchedQuery.isLoading ? (
                  <tr>
                    <td colSpan={6} className="px-3 py-8 text-center text-muted-foreground">
                      <Loader2 className="mx-auto h-4 w-4 animate-spin" />
                    </td>
                  </tr>
                ) : watched && watched.items.length > 0 ? (
                  watched.items.map((row) => (
                    <tr key={row.id} className="text-xs">
                      <td className="px-3 py-2 font-medium text-foreground">{row.symbol}</td>
                      <td className="px-3 py-2 text-muted-foreground">
                        {row.market ?? "—"}
                      </td>
                      <td className="px-3 py-2 text-muted-foreground">
                        {row.registeredBy ?? "—"}
                      </td>
                      <td className="px-3 py-2 text-muted-foreground">
                        {formatDateTime(row.lastViewedAt)}
                      </td>
                      <td className="px-3 py-2 text-muted-foreground">
                        {formatDateTime(row.lastPolledAt)}
                      </td>
                      <td className="px-3 py-2 text-red-600 dark:text-red-400">
                        {row.lastError ?? ""}
                      </td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={6} className="px-3 py-8 text-center text-sm text-muted-foreground">
                      {t("admin.stockpulse.noWatched")}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </AdminLayout>
  );
}

/* --- helpers --- */

function StatCard({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-border bg-card px-3 py-2.5">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1">{value}</div>
    </div>
  );
}

function Th({ children }: { children: React.ReactNode }) {
  return (
    <th className="px-3 py-2 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground">
      {children}
    </th>
  );
}

function formatDateTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString();
}
