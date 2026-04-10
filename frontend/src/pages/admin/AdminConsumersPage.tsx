import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Loader2,
  Plus,
  Trash2,
  Copy,
  Check,
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  Webhook,
  Activity,
  Clock,
  Zap,
  CircleAlert,
  CircleCheck,
  CircleX,
} from "lucide-react";
import {
  getConsumers,
  createConsumer,
  deleteConsumer,
  getConsumerUsage,
  testConsumerWebhook,
} from "@/api/admin";
import type {
  ConsumerRaw,
  ConsumerCreateRaw,
  WebhookSummaryRaw,
} from "@/api/admin";
import { getErrorMessage } from "@/api/client";
import { StatusBadge } from "@/components/admin/StatusBadge";
import { AdminLayout } from "@/components/admin/AdminLayout";

/* ------------------------------------------------------------------ */
/*  ConsumerDetailPanel — expanded row showing usage & webhook stats   */
/* ------------------------------------------------------------------ */

function WebhookCard({
  webhook,
  consumerId,
}: {
  webhook: WebhookSummaryRaw;
  consumerId: string;
}) {
  const { t } = useTranslation();
  const [testResult, setTestResult] = useState<{
    success: boolean;
    error?: string | null;
    statusCode?: number | null;
  } | null>(null);

  const testMutation = useMutation({
    mutationFn: () => testConsumerWebhook(consumerId, webhook.id),
    onSuccess: (data) => setTestResult(data),
    onError: (err) =>
      setTestResult({ success: false, error: getErrorMessage(err) }),
  });

  const failureStatus =
    webhook.consecutiveFailures > 0
      ? webhook.consecutiveFailures >= 5
        ? "error"
        : "warning"
      : "healthy";

  return (
    <div className="rounded-md border border-border bg-background p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <Webhook className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
            <code className="truncate text-xs text-foreground">
              {webhook.url}
            </code>
          </div>
          <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <StatusBadge
              status={webhook.isActive ? "active" : "inactive"}
            />
            <StatusBadge status={failureStatus} />
            {webhook.consecutiveFailures > 0 && (
              <span className="text-amber-600 dark:text-amber-400">
                {t("admin.consecutiveFailures", { count: webhook.consecutiveFailures })}
              </span>
            )}
          </div>
          <div className="mt-1.5 flex flex-wrap gap-1">
            {webhook.events.map((evt) => (
              <span
                key={evt}
                className="inline-flex rounded bg-blue-50 px-1.5 py-0.5 text-[10px] font-medium text-blue-700 dark:bg-blue-900/30 dark:text-blue-300"
              >
                {evt}
              </span>
            ))}
          </div>
          <div className="mt-1.5 flex items-center gap-3 text-xs text-muted-foreground">
            {webhook.lastTriggeredAt && (
              <span className="flex items-center gap-1">
                <Clock className="h-3 w-3" />
                {t("admin.lastTriggered")} {new Date(webhook.lastTriggeredAt).toLocaleString()}
              </span>
            )}
            {webhook.createdAt && (
              <span>
                {t("admin.created")} {new Date(webhook.createdAt).toLocaleDateString()}
              </span>
            )}
          </div>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1.5">
          <button
            onClick={() => {
              setTestResult(null);
              testMutation.mutate();
            }}
            disabled={testMutation.isPending || !webhook.isActive}
            className="flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs font-medium text-foreground hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50"
          >
            {testMutation.isPending ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <Zap className="h-3 w-3" />
            )}
            {t("admin.testConnection")}
          </button>
          {testResult && (
            <div className="flex items-center gap-1 text-xs">
              {testResult.success ? (
                <>
                  <CircleCheck className="h-3 w-3 text-green-600" />
                  <span className="text-green-600 dark:text-green-400">
                    {t("admin.testSuccess")}{testResult.statusCode ? ` (${testResult.statusCode})` : ""}
                  </span>
                </>
              ) : (
                <>
                  <CircleX className="h-3 w-3 text-red-600" />
                  <span className="max-w-[200px] truncate text-red-600 dark:text-red-400">
                    {testResult.error ?? t("admin.testFailed")}
                  </span>
                </>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function ConsumerDetailPanel({ consumer }: { consumer: ConsumerRaw }) {
  const { t } = useTranslation();
  const { data: usage, isLoading } = useQuery({
    queryKey: ["admin", "consumer-usage", consumer.id],
    queryFn: () => getConsumerUsage(consumer.id),
    staleTime: 30_000,
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-6">
        <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (!usage) {
    return (
      <div className="py-4 text-center text-sm text-muted-foreground">
        {t("admin.loadUsageError")}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4 px-3 pb-4 pt-1">
      {/* Stats row */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard
          icon={<Webhook className="h-4 w-4 text-blue-500" />}
          label="Webhooks"
          value={String(usage.webhookCount)}
        />
        <StatCard
          icon={<Activity className="h-4 w-4 text-green-500" />}
          label={t("admin.statusLabel")}
          value={usage.isActive ? t("admin.active") : t("admin.inactive")}
          valueClass={usage.isActive ? "text-green-600 dark:text-green-400" : "text-gray-500"}
        />
        <StatCard
          icon={<Clock className="h-4 w-4 text-amber-500" />}
          label={t("admin.lastUsedLabel")}
          value={
            usage.lastUsedAt
              ? formatRelativeTime(new Date(usage.lastUsedAt), t)
              : t("admin.neverUsed")
          }
        />
        <StatCard
          icon={<Clock className="h-4 w-4 text-purple-500" />}
          label={t("admin.createdAtLabel")}
          value={
            usage.createdAt
              ? new Date(usage.createdAt).toLocaleDateString()
              : "-"
          }
        />
      </div>

      {/* Webhook list */}
      {usage.webhooks.length > 0 ? (
        <div className="flex flex-col gap-2">
          <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            {t("admin.webhookEndpoints")}
          </h4>
          {usage.webhooks.map((wh) => (
            <WebhookCard
              key={wh.id}
              webhook={wh}
              consumerId={consumer.id}
            />
          ))}
        </div>
      ) : (
        <div className="flex items-center gap-2 rounded-md border border-dashed border-border p-4 text-sm text-muted-foreground">
          <CircleAlert className="h-4 w-4" />
          {t("admin.noWebhooks")}
        </div>
      )}
    </div>
  );
}

function StatCard({
  icon,
  label,
  value,
  valueClass,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  valueClass?: string;
}) {
  return (
    <div className="flex items-center gap-2.5 rounded-md border border-border bg-background p-2.5">
      {icon}
      <div className="min-w-0">
        <div className="text-[11px] text-muted-foreground">{label}</div>
        <div
          className={`truncate text-sm font-semibold ${valueClass ?? "text-foreground"}`}
        >
          {value}
        </div>
      </div>
    </div>
  );
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function formatRelativeTime(date: Date, t: any): string {
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMin = Math.floor(diffMs / 60_000);
  if (diffMin < 1) return t("admin.justNow");
  if (diffMin < 60) return t("admin.minutesAgo", { count: diffMin });
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return t("admin.hoursAgo", { count: diffHr });
  const diffDay = Math.floor(diffHr / 24);
  if (diffDay < 30) return t("admin.daysAgo", { count: diffDay });
  return date.toLocaleDateString();
}

/* ------------------------------------------------------------------ */
/*  Main consumers content                                             */
/* ------------------------------------------------------------------ */

function ConsumersContent() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [formName, setFormName] = useState("");
  const [formDesc, setFormDesc] = useState("");
  const [error, setError] = useState("");
  const [newKey, setNewKey] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const { data: consumers, isLoading } = useQuery({
    queryKey: ["admin", "consumers"],
    queryFn: getConsumers,
  });

  const createMutation = useMutation({
    mutationFn: createConsumer,
    onSuccess: (data: ConsumerCreateRaw) => {
      void queryClient.invalidateQueries({ queryKey: ["admin", "consumers"] });
      setNewKey(data.rawApiKey);
      setShowForm(false);
      setFormName("");
      setFormDesc("");
      setError("");
    },
    onError: (err) => setError(getErrorMessage(err)),
  });

  const deleteMutation = useMutation({
    mutationFn: deleteConsumer,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["admin", "consumers"] });
    },
    onError: (err) => setError(getErrorMessage(err)),
  });

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    createMutation.mutate({
      name: formName,
      description: formDesc || undefined,
    });
  };

  const handleCopy = async () => {
    if (newKey) {
      try {
        await navigator.clipboard.writeText(newKey);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      } catch {
        // Fallback: select the text for manual copy
        const codeEl = document.querySelector<HTMLElement>("[data-api-key]");
        if (codeEl) {
          const range = document.createRange();
          range.selectNodeContents(codeEl);
          const selection = window.getSelection();
          selection?.removeAllRanges();
          selection?.addRange(range);
        }
      }
    }
  };

  const toggleExpand = (id: string) => {
    setExpandedId((prev) => (prev === id ? null : id));
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
          {t("admin.consumers")}
        </h3>
        <button
          onClick={() => {
            setShowForm(!showForm);
            setNewKey(null);
          }}
          className="flex items-center gap-1.5 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground"
        >
          <Plus className="h-4 w-4" />
          {t("admin.createConsumer")}
        </button>
      </div>

      {/* New API key display */}
      {newKey && (
        <div className="rounded-lg border-2 border-amber-400 bg-amber-50 p-4 dark:border-amber-600 dark:bg-amber-900/20">
          <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-amber-800 dark:text-amber-300">
            <AlertTriangle className="h-4 w-4" />
            {t("admin.apiKeyWarning")}
          </div>
          <div className="flex items-center gap-2">
            <code data-api-key className="flex-1 break-all rounded bg-white px-3 py-2 text-sm font-mono text-foreground dark:bg-gray-900">
              {newKey}
            </code>
            <button
              onClick={() => void handleCopy()}
              className="shrink-0 rounded-md border border-border p-2 hover:bg-muted"
            >
              {copied ? (
                <Check className="h-4 w-4 text-green-600" />
              ) : (
                <Copy className="h-4 w-4 text-muted-foreground" />
              )}
            </button>
          </div>
        </div>
      )}

      {showForm && (
        <form
          onSubmit={handleSubmit}
          className="flex flex-col gap-3 rounded-lg border border-border bg-card p-4"
        >
          {error && (
            <div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
              {error}
            </div>
          )}
          <input
            type="text"
            value={formName}
            onChange={(e) => setFormName(e.target.value)}
            placeholder={t("admin.consumerName")}
            required
            className="rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground outline-none focus:border-primary"
          />
          <input
            type="text"
            value={formDesc}
            onChange={(e) => setFormDesc(e.target.value)}
            placeholder={t("admin.consumerDescription")}
            className="rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground outline-none focus:border-primary"
          />
          <div className="flex gap-2">
            <button
              type="submit"
              disabled={createMutation.isPending}
              className="flex items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
            >
              {createMutation.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                t("admin.createConsumer")
              )}
            </button>
            <button
              type="button"
              onClick={() => setShowForm(false)}
              className="rounded-md border border-border px-4 py-2 text-sm text-foreground hover:bg-accent"
            >
              {t("common.cancel")}
            </button>
          </div>
        </form>
      )}

      <div className="rounded-lg border border-border bg-card">
        {(!consumers || consumers.length === 0) ? (
          <div className="py-8 text-center text-sm text-muted-foreground">
            {t("admin.noConsumers")}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border">
                  <th className="w-8 px-3 py-2.5" />
                  <th className="px-3 py-2.5 text-left font-medium text-muted-foreground">
                    {t("admin.consumerName")}
                  </th>
                  <th className="px-3 py-2.5 text-left font-medium text-muted-foreground">
                    {t("admin.keyPrefix")}
                  </th>
                  <th className="px-3 py-2.5 text-right font-medium text-muted-foreground">
                    {t("admin.rateLimit")}
                  </th>
                  <th className="px-3 py-2.5 text-left font-medium text-muted-foreground">
                    {t("admin.status")}
                  </th>
                  <th className="px-3 py-2.5 text-left font-medium text-muted-foreground">
                    {t("admin.lastUsed")}
                  </th>
                  <th className="w-10 px-3 py-2.5" />
                </tr>
              </thead>
              <tbody>
                {consumers.map((consumer) => {
                  const isExpanded = expandedId === consumer.id;
                  return (
                    <ConsumerRow
                      key={consumer.id}
                      consumer={consumer}
                      isExpanded={isExpanded}
                      onToggle={() => toggleExpand(consumer.id)}
                      onDelete={() => deleteMutation.mutate(consumer.id)}
                      deleteDisabled={deleteMutation.isPending}
                    />
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  ConsumerRow — table row with expandable detail panel               */
/* ------------------------------------------------------------------ */

function ConsumerRow({
  consumer,
  isExpanded,
  onToggle,
  onDelete,
  deleteDisabled,
}: {
  consumer: ConsumerRaw;
  isExpanded: boolean;
  onToggle: () => void;
  onDelete: () => void;
  deleteDisabled: boolean;
}) {
  const { t } = useTranslation();
  return (
    <>
      <tr
        className={`border-b border-border cursor-pointer hover:bg-muted/50 ${
          isExpanded ? "bg-muted/30" : ""
        }`}
        onClick={onToggle}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            onToggle();
          }
        }}
        tabIndex={0}
        role="button"
        aria-expanded={isExpanded}
      >
        <td className="px-3 py-2.5 text-muted-foreground">
          {isExpanded ? (
            <ChevronDown className="h-4 w-4" />
          ) : (
            <ChevronRight className="h-4 w-4" />
          )}
        </td>
        <td className="px-3 py-2.5 font-medium text-foreground">
          {consumer.name}
          {consumer.description && (
            <span className="ml-2 text-xs text-muted-foreground">
              {consumer.description}
            </span>
          )}
        </td>
        <td className="px-3 py-2.5">
          <code className="rounded bg-muted px-1.5 py-0.5 text-xs">
            {consumer.apiKeyPrefix}...
          </code>
        </td>
        <td className="px-3 py-2.5 text-right">{consumer.rateLimit}/min</td>
        <td className="px-3 py-2.5">
          <StatusBadge status={consumer.isActive ? "active" : "inactive"} />
        </td>
        <td className="px-3 py-2.5 text-muted-foreground">
          {consumer.lastUsedAt
            ? formatRelativeTime(new Date(consumer.lastUsedAt), t)
            : "-"}
        </td>
        <td className="px-3 py-2.5">
          {consumer.isActive ? (
            <button
              onClick={(e) => {
                e.stopPropagation();
                if (window.confirm(t("admin.confirmDeleteConsumer"))) {
                  onDelete();
                }
              }}
              disabled={deleteDisabled}
              className="rounded p-1.5 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          ) : null}
        </td>
      </tr>
      {isExpanded && (
        <tr className="border-b border-border last:border-0">
          <td colSpan={7} className="bg-muted/20 p-0">
            <ConsumerDetailPanel consumer={consumer} />
          </td>
        </tr>
      )}
    </>
  );
}

/* ------------------------------------------------------------------ */
/*  Page wrapper                                                       */
/* ------------------------------------------------------------------ */

export default function AdminConsumersPage() {
  return (
    <AdminLayout>
      <ConsumersContent />
    </AdminLayout>
  );
}
