import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery, useMutation } from "@tanstack/react-query";
import * as Tabs from "@radix-ui/react-tabs";
import {
  Loader2,
  Play,
  Pause,
  ListOrdered,
  Cog,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import {
  getPipelineEvents,
  triggerPoll,
  setConcurrency,
  pausePipeline,
  resumePipeline,
  resetCircuitBreaker,
  getQueueItems,
} from "@/api/admin";
import type { PipelineEventRaw, QueueArticle } from "@/api/admin";
import { useQueueStream } from "@/hooks/useQueueStream";
import { StatsCard } from "@/components/admin/StatsCard";
import { StatusBadge } from "@/components/admin/StatusBadge";
import { DataTable, type Column } from "@/components/admin/DataTable";
import { AdminLayout } from "@/components/admin/AdminLayout";

/* ---------- helpers ---------- */

function formatElapsed(startTimestamp?: string): string {
  if (!startTimestamp) return "-";
  const startSec = parseFloat(startTimestamp);
  if (Number.isNaN(startSec)) return "-";
  const elapsed = Math.max(0, Math.floor(Date.now() / 1000 - startSec));
  if (elapsed < 60) return `${elapsed}s`;
  return `${Math.floor(elapsed / 60)}m ${elapsed % 60}s`;
}

/* ---------- Queue Monitor ---------- */

function QueueMonitor() {
  const { t } = useTranslation();
  const { data: queue, connected, refresh } = useQueueStream();
  const [concurrencyInput, setConcurrencyInput] = useState<string>("");
  const [activeTab, setActiveTab] = useState("queued");

  // Pagination state for queued tab
  const [queuePage, setQueuePage] = useState(1);
  const [queuePageSize, setQueuePageSize] = useState(50);

  const { data: paginatedQueue } = useQuery({
    queryKey: ["admin", "queue-items", queuePage, queuePageSize],
    queryFn: () => getQueueItems(queuePage, queuePageSize),
    refetchInterval: 10_000,
    enabled: activeTab === "queued",
  });

  const concurrencyMutation = useMutation({
    mutationFn: (value: number) => setConcurrency(value),
  });

  const pauseMutation = useMutation({
    mutationFn: () => pausePipeline(),
  });

  const resumeMutation = useMutation({
    mutationFn: () => resumePipeline(),
  });

  const resetCBMutation = useMutation({
    mutationFn: () => resetCircuitBreaker(),
    onSuccess: () => {
      // Force refresh to get latest state
      refresh();
    },
  });

  if (!queue) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const handleApplyConcurrency = () => {
    const val = parseInt(concurrencyInput, 10);
    if (val >= 1 && val <= 50) {
      concurrencyMutation.mutate(val);
    }
  };

  const handleTogglePause = () => {
    if (queue.paused) {
      resumeMutation.mutate();
    } else {
      pauseMutation.mutate();
    }
  };

  const tabTriggerClass =
    "px-3 py-2 text-sm font-medium text-muted-foreground data-[state=active]:text-foreground data-[state=active]:border-b-2 data-[state=active]:border-primary outline-none";

  /* Column defs */
  const queuedColumns: Column<QueueArticle>[] = [
    {
      header: t("admin.queue.position"),
      accessor: (r) => r.position ?? "-",
      className: "w-16 text-center",
    },
    {
      header: t("admin.queue.priority", "Priority"),
      accessor: (r) => (
        <span
          className={`inline-block rounded px-1.5 py-0.5 text-xs font-medium ${
            r.priority === "high"
              ? "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400"
              : "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400"
          }`}
        >
          {r.priority === "high" ? "HIGH" : "LOW"}
        </span>
      ),
      className: "w-20",
    },
    {
      header: t("admin.articleId"),
      accessor: (r) => (
        <span className="font-mono text-xs">
          {r.article_id?.slice(0, 8) ?? "-"}
        </span>
      ),
    },
    {
      header: t("admin.articleTitle", "Title"),
      accessor: (r) => (
        <span className="max-w-[300px] truncate" title={r.title}>
          {r.title || "-"}
        </span>
      ),
    },
    {
      header: t("admin.queue.waitTime"),
      accessor: (r) => formatElapsed(r.enqueued_at),
    },
  ];

  const processingColumns: Column<QueueArticle>[] = [
    {
      header: t("admin.articleId"),
      accessor: (r) => (
        <span className="font-mono text-xs">
          {r.article_id?.slice(0, 8) ?? "-"}
        </span>
      ),
    },
    {
      header: t("admin.articleTitle", "Title"),
      accessor: (r) => (
        <span className="max-w-[300px] truncate" title={r.title}>
          {r.title || "-"}
        </span>
      ),
    },
    {
      header: t("admin.queue.currentStage"),
      accessor: (r) =>
        r.current_stage ? <StatusBadge status={r.current_stage} /> : "-",
    },
    {
      header: t("admin.queue.elapsed"),
      accessor: (r) => formatElapsed(r.started_at),
    },
  ];

  const recentColumns: Column<QueueArticle>[] = [
    {
      header: t("admin.articleId"),
      accessor: (r) => (
        <span className="font-mono text-xs">
          {r.article_id?.slice(0, 8) ?? "-"}
        </span>
      ),
    },
    {
      header: t("admin.articleTitle", "Title"),
      accessor: (r) => (
        <span className="max-w-[300px] truncate" title={r.title}>
          {r.title || "-"}
        </span>
      ),
    },
    {
      header: t("admin.status"),
      accessor: (r) => (
        <StatusBadge status={r.status ?? "unknown"} />
      ),
    },
    {
      header: t("admin.duration"),
      accessor: (r) =>
        r.duration_ms != null ? `${r.duration_ms}ms` : "-",
      className: "text-right",
    },
    {
      header: t("admin.errorDetail"),
      accessor: (r) =>
        r.error ? (
          <span
            className="max-w-[200px] truncate text-xs text-red-600 dark:text-red-400"
            title={r.error}
          >
            {r.error}
          </span>
        ) : null,
    },
  ];

  return (
    <div className="flex flex-col gap-4">
      {/* Paused banner */}
      {queue.paused && (
        <div className="flex items-center gap-2 rounded-md bg-amber-50 p-3 text-sm text-amber-700 dark:bg-amber-900/20 dark:text-amber-400">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          {t("admin.queue.pausedBanner")}
        </div>
      )}

      {/* Circuit breaker banner */}
      {queue.circuitBreaker?.state === "open" && (
        <div className="flex items-center gap-2 rounded-md bg-red-50 p-3 text-sm text-red-700 dark:bg-red-900/20 dark:text-red-400">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          <span className="flex-1">
            {t("admin.queue.circuitBreakerOpen", {
              defaultValue: "Circuit breaker OPEN — pipeline paused due to {{count}} consecutive failures. LLM provider may be down.",
              count: queue.circuitBreaker.consecutiveFailures,
            })}
          </span>
          <button
            onClick={() => resetCBMutation.mutate()}
            disabled={resetCBMutation.isPending}
            className="shrink-0 rounded bg-red-600 px-3 py-1 text-xs font-medium text-white hover:bg-red-700 disabled:opacity-50 dark:bg-red-700 dark:hover:bg-red-600"
          >
            {resetCBMutation.isPending ? t("common.resetting", "Resetting...") : t("common.reset", "Reset")}
          </button>
        </div>
      )}
      {queue.circuitBreaker?.state === "half_open" && (
        <div className="flex items-center gap-2 rounded-md bg-amber-50 p-3 text-sm text-amber-700 dark:bg-amber-900/20 dark:text-amber-400">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          {t("admin.queue.circuitBreakerHalfOpen", "Circuit breaker probing — testing if LLM provider has recovered...")}
        </div>
      )}

      {/* Stats row */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatsCard
          label={t("admin.queue.queued")}
          value={queue.counts.queued}
          {...((queue.counts.queued_high != null || queue.counts.queued_low != null)
            ? { subtitle: `H: ${queue.counts.queued_high ?? 0} / L: ${queue.counts.queued_low ?? 0}` }
            : {})}
          icon={ListOrdered}
        />
        <StatsCard
          label={t("admin.queue.processing")}
          value={queue.counts.processing}
          icon={Cog}
        />
        <StatsCard
          label={t("queue.completed", "Completed")}
          value={queue.counts.completed}
          icon={CheckCircle2}
        />
        <StatsCard
          label={t("queue.failed", "Failed")}
          value={queue.counts.failed}
          icon={XCircle}
        />
      </div>

      {/* Controls row */}
      <div className="flex flex-wrap items-center gap-3">
        <button
          onClick={handleTogglePause}
          disabled={pauseMutation.isPending || resumeMutation.isPending}
          className={`flex items-center gap-1.5 rounded-md px-3 py-2 text-sm font-medium disabled:opacity-50 ${
            queue.paused
              ? "bg-green-600 text-white hover:bg-green-700"
              : "bg-amber-600 text-white hover:bg-amber-700"
          }`}
        >
          {pauseMutation.isPending || resumeMutation.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : queue.paused ? (
            <Play className="h-4 w-4" />
          ) : (
            <Pause className="h-4 w-4" />
          )}
          {queue.paused ? t("admin.queue.resume") : t("admin.queue.pause")}
        </button>

        <div className="flex items-center gap-2">
          <span className="text-sm text-muted-foreground">
            {t("admin.queue.concurrency")}:
          </span>
          <span className="text-sm text-foreground">
            {t("admin.queue.active")} {queue.concurrency.active} / {t("admin.queue.target")} {queue.concurrency.target}
          </span>
          <input
            type="number"
            min={1}
            max={50}
            value={concurrencyInput}
            onChange={(e) => setConcurrencyInput(e.target.value)}
            placeholder={String(queue.concurrency.target)}
            className="w-20 rounded-md border border-border bg-background px-2 py-1.5 text-sm text-foreground outline-none focus:border-primary"
          />
          <button
            onClick={handleApplyConcurrency}
            disabled={
              concurrencyMutation.isPending ||
              !concurrencyInput ||
              parseInt(concurrencyInput, 10) < 1 ||
              parseInt(concurrencyInput, 10) > 50
            }
            className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground disabled:opacity-50"
          >
            {concurrencyMutation.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              t("admin.queue.apply")
            )}
          </button>
        </div>

        {/* SSE connection indicator */}
        <div className="ml-auto flex items-center gap-1.5">
          <div
            className={`h-2 w-2 rounded-full ${
              connected ? "bg-green-500" : "bg-gray-400"
            }`}
          />
          <span className="text-xs text-muted-foreground">
            {connected ? t("queue.live", "Live") : t("queue.polling", "Polling")}
          </span>
        </div>
      </div>

      {/* Queue tabs */}
      <Tabs.Root value={activeTab} onValueChange={setActiveTab}>
        <Tabs.List className="flex gap-1 border-b border-border">
          <Tabs.Trigger value="queued" className={tabTriggerClass}>
            {t("admin.queue.queued")} ({queue.queued.length})
          </Tabs.Trigger>
          <Tabs.Trigger value="processing" className={tabTriggerClass}>
            {t("admin.queue.processing")} ({queue.processing.length})
          </Tabs.Trigger>
          <Tabs.Trigger value="recent" className={tabTriggerClass}>
            {t("admin.queue.recent")} ({queue.recent.length})
          </Tabs.Trigger>
        </Tabs.List>

        <Tabs.Content value="queued">
          <div className="mt-3 flex flex-col gap-3">
            {/* Page size selector + pagination info */}
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <span className="text-sm text-muted-foreground">
                  {t("admin.queue.pageSize", "Page size")}:
                </span>
                <select
                  value={queuePageSize}
                  onChange={(e) => {
                    setQueuePageSize(Number(e.target.value));
                    setQueuePage(1);
                  }}
                  className="rounded-md border border-border bg-background px-2 py-1 text-sm text-foreground outline-none focus:border-primary"
                >
                  {[25, 50, 100].map((n) => (
                    <option key={n} value={n}>{n}</option>
                  ))}
                </select>
              </div>
              {paginatedQueue && (
                <div className="flex items-center gap-2">
                  <span className="text-sm text-muted-foreground">
                    {t("admin.queue.pageInfo", "Page {{page}} of {{total}}", {
                      page: paginatedQueue.page,
                      total: Math.max(1, Math.ceil(paginatedQueue.total / paginatedQueue.page_size)),
                    })}
                  </span>
                  <button
                    onClick={() => setQueuePage((p) => Math.max(1, p - 1))}
                    disabled={queuePage <= 1}
                    className="rounded-md border border-border p-1 text-muted-foreground hover:bg-accent disabled:opacity-30"
                  >
                    <ChevronLeft className="h-4 w-4" />
                  </button>
                  <button
                    onClick={() =>
                      setQueuePage((p) =>
                        p < Math.ceil(paginatedQueue.total / paginatedQueue.page_size)
                          ? p + 1
                          : p,
                      )
                    }
                    disabled={
                      !paginatedQueue ||
                      queuePage >= Math.ceil(paginatedQueue.total / paginatedQueue.page_size)
                    }
                    className="rounded-md border border-border p-1 text-muted-foreground hover:bg-accent disabled:opacity-30"
                  >
                    <ChevronRight className="h-4 w-4" />
                  </button>
                </div>
              )}
            </div>
            <div className="rounded-lg border border-border bg-card">
              <DataTable
                columns={queuedColumns}
                data={paginatedQueue?.items ?? queue.queued}
                keyExtractor={(r) => r.article_id}
                emptyMessage={t("admin.queue.noItems")}
              />
            </div>
          </div>
        </Tabs.Content>

        <Tabs.Content value="processing">
          <div className="mt-3 rounded-lg border border-border bg-card">
            <DataTable
              columns={processingColumns}
              data={queue.processing}
              keyExtractor={(r) => r.article_id}
              emptyMessage={t("admin.queue.noItems")}
            />
          </div>
        </Tabs.Content>

        <Tabs.Content value="recent">
          <div className="mt-3 rounded-lg border border-border bg-card">
            <DataTable
              columns={recentColumns}
              data={queue.recent}
              keyExtractor={(r) => r.article_id + (r.completed_at ?? "")}
              emptyMessage={t("admin.queue.noItems")}
            />
          </div>
        </Tabs.Content>
      </Tabs.Root>
    </div>
  );
}

/* ---------- Pipeline Events (existing) ---------- */

function PipelineEvents() {
  const { t } = useTranslation();
  const [stageFilter, setStageFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");

  const { data: events, isLoading } = useQuery({
    queryKey: ["admin", "pipeline-events", stageFilter],
    queryFn: () =>
      getPipelineEvents({
        limit: 50,
        stage: stageFilter === "all" ? undefined : stageFilter,
      }),
    refetchInterval: 10_000,
  });

  const filtered = (events ?? []).filter(
    (e) => statusFilter === "all" || e.status === statusFilter,
  );

  const eventColumns: Column<PipelineEventRaw>[] = [
    { header: t("admin.stage"), accessor: (r) => r.stage },
    {
      header: t("admin.status"),
      accessor: (r) => <StatusBadge status={r.status} />,
    },
    {
      header: t("admin.duration"),
      accessor: (r) =>
        r.duration_ms != null ? `${r.duration_ms}ms` : "-",
      className: "text-right",
    },
    {
      header: t("admin.articleId"),
      accessor: (r) => (
        <span className="font-mono text-xs">
          {r.article_id?.slice(0, 8) ?? "-"}
        </span>
      ),
    },
    {
      header: t("admin.createdAt"),
      accessor: (r) =>
        new Date(r.created_at).toLocaleString([], {
          month: "short",
          day: "numeric",
          hour: "2-digit",
          minute: "2-digit",
        }),
    },
    {
      header: t("admin.errorDetail"),
      accessor: (r) =>
        r.error ? (
          <span
            className="max-w-[200px] truncate text-xs text-red-600 dark:text-red-400"
            title={r.error}
          >
            {r.error}
          </span>
        ) : null,
    },
  ];

  return (
    <div className="flex flex-col gap-4">
      {/* Filters */}
      <div className="flex flex-wrap gap-3">
        <select
          value={stageFilter}
          onChange={(e) => setStageFilter(e.target.value)}
          className="rounded-md border border-border bg-background px-3 py-1.5 text-sm text-foreground outline-none focus:border-primary"
        >
          <option value="all">{t("admin.allStages")}</option>
          <option value="classify">classify</option>
          <option value="fetch">fetch</option>
          <option value="analyze">analyze</option>
          <option value="embed">embed</option>
        </select>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="rounded-md border border-border bg-background px-3 py-1.5 text-sm text-foreground outline-none focus:border-primary"
        >
          <option value="all">{t("admin.allStatuses")}</option>
          <option value="success">success</option>
          <option value="error">error</option>
          <option value="skip">skip</option>
        </select>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : (
        <div className="rounded-lg border border-border bg-card">
          <DataTable
            columns={eventColumns}
            data={filtered}
            keyExtractor={(r) => r.id}
            emptyMessage={t("admin.noEvents")}
          />
        </div>
      )}
    </div>
  );
}

/* ---------- Page ---------- */

function PipelineContent() {
  const { t } = useTranslation();

  const pollMutation = useMutation({
    mutationFn: triggerPoll,
  });

  return (
    <div className="flex flex-col gap-6">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="text-lg font-semibold text-foreground">
          {t("admin.pipeline")}
        </h3>
        <button
          onClick={() => pollMutation.mutate()}
          disabled={pollMutation.isPending}
          className="flex items-center gap-1.5 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
        >
          {pollMutation.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Play className="h-4 w-4" />
          )}
          {t("admin.triggerPoll")}
        </button>
      </div>

      {pollMutation.isSuccess && (
        <div className="rounded-md bg-green-50 p-3 text-sm text-green-700 dark:bg-green-900/20 dark:text-green-400">
          {t("admin.pollTriggered")}
        </div>
      )}

      {/* Queue Monitor */}
      <QueueMonitor />

      {/* Divider */}
      <hr className="border-border" />

      {/* Pipeline Events */}
      <h4 className="text-base font-semibold text-foreground">
        {t("admin.pipelineEvents", "Pipeline Events")}
      </h4>
      <PipelineEvents />
    </div>
  );
}

export default function AdminPipelinePage() {
  return (
    <AdminLayout>
      <PipelineContent />
    </AdminLayout>
  );
}
