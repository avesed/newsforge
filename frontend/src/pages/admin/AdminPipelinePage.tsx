import { useState, useCallback } from "react";
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
  getRecentItems,
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

function formatDuration(ms?: string | number | null): string {
  if (ms == null) return "-";
  const val = typeof ms === "string" ? parseFloat(ms) : ms;
  if (Number.isNaN(val)) return "-";
  if (val < 1000) return `${Math.round(val)}ms`;
  if (val < 60_000) return `${(val / 1000).toFixed(1)}s`;
  const mins = Math.floor(val / 60_000);
  const secs = Math.round((val % 60_000) / 1000);
  return `${mins}m ${secs}s`;
}

/* ---------- Shared pagination component ---------- */

function Pagination({
  page,
  totalPages,
  pageSize,
  pageSizeOptions = [25, 50, 100],
  onPageChange,
  onPageSizeChange,
  t,
}: {
  page: number;
  totalPages: number;
  pageSize: number;
  pageSizeOptions?: number[];
  onPageChange: (page: number) => void;
  onPageSizeChange: (size: number) => void;
  t: (key: string, opts?: any) => string;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <div className="flex items-center gap-2">
        <span className="text-sm text-muted-foreground">
          {t("admin.queue.pageSize")}:
        </span>
        <select
          value={pageSize}
          onChange={(e) => onPageSizeChange(Number(e.target.value))}
          className="rounded-md border border-border bg-background px-2 py-1 text-sm text-foreground outline-none focus:border-primary"
        >
          {pageSizeOptions.map((n) => (
            <option key={n} value={n}>
              {n}
            </option>
          ))}
        </select>
      </div>
      <div className="flex items-center gap-2">
        <span className="text-sm text-muted-foreground">
          {t("admin.queue.pageInfo", {
            page,
            total: totalPages,
            defaultValue: "Page {{page}} of {{total}}",
          })}
        </span>
        <button
          onClick={() => onPageChange(Math.max(1, page - 1))}
          disabled={page <= 1}
          className="rounded-md border border-border p-1 text-muted-foreground hover:bg-accent disabled:opacity-30"
        >
          <ChevronLeft className="h-4 w-4" />
        </button>
        <button
          onClick={() => onPageChange(Math.min(totalPages, page + 1))}
          disabled={page >= totalPages}
          className="rounded-md border border-border p-1 text-muted-foreground hover:bg-accent disabled:opacity-30"
        >
          <ChevronRight className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}

/* ---------- Clickable title cell ---------- */

function TitleCell({ title }: { title?: string }) {
  const [expanded, setExpanded] = useState(false);
  if (!title) return <span>-</span>;
  return (
    <button
      type="button"
      onClick={() => setExpanded((v) => !v)}
      className={`text-left ${expanded ? "whitespace-normal break-all" : "block w-full truncate"}`}
      title={expanded ? undefined : title}
    >
      {title}
    </button>
  );
}

/* ---------- Queue Monitor ---------- */

function QueueMonitor() {
  const { t } = useTranslation();
  const { data: queue, connected, refresh } = useQueueStream();
  const [concurrencyInput, setConcurrencyInput] = useState<string>("");
  const [activeTab, setActiveTab] = useState("queued");

  // Pagination state — queued tab
  const [queuePage, setQueuePage] = useState(1);
  const [queuePageSize, setQueuePageSize] = useState(50);

  // Pagination state — recent tab
  const [recentPage, setRecentPage] = useState(1);
  const [recentPageSize, setRecentPageSize] = useState(50);

  const { data: paginatedQueue } = useQuery({
    queryKey: ["admin", "queue-items", queuePage, queuePageSize],
    queryFn: () => getQueueItems(queuePage, queuePageSize),
    refetchInterval: 10_000,
    enabled: activeTab === "queued",
  });

  const { data: paginatedRecent } = useQuery({
    queryKey: ["admin", "recent-items", recentPage, recentPageSize],
    queryFn: () => getRecentItems(recentPage, recentPageSize),
    refetchInterval: 10_000,
    enabled: activeTab === "recent",
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
    mutationFn: (purpose?: string) => resetCircuitBreaker(purpose),
    onSuccess: () => refresh(),
  });

  const handleQueuePageSizeChange = useCallback((size: number) => {
    setQueuePageSize(size);
    setQueuePage(1);
  }, []);

  const handleRecentPageSizeChange = useCallback((size: number) => {
    setRecentPageSize(size);
    setRecentPage(1);
  }, []);

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

  /* Column defs — title column uses flex-1 to fill remaining space */
  const queuedColumns: Column<QueueArticle>[] = [
    {
      header: t("admin.queue.position"),
      accessor: (r) => r.position ?? "-",
      className: "w-12 shrink-0 text-center",
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
      className: "w-16 shrink-0",
    },
    {
      header: t("admin.articleId"),
      accessor: (r) => (
        <span className="font-mono text-xs">
          {r.article_id?.slice(0, 8) ?? "-"}
        </span>
      ),
      className: "w-20 shrink-0",
    },
    {
      header: t("admin.articleTitle", "Title"),
      accessor: (r) => <TitleCell title={r.title} />,
      className: "min-w-0",
    },
    {
      header: t("admin.queue.waitTime"),
      accessor: (r) => formatElapsed(r.enqueued_at),
      className: "w-20 shrink-0 text-right",
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
      className: "w-20 shrink-0",
    },
    {
      header: t("admin.articleTitle", "Title"),
      accessor: (r) => <TitleCell title={r.title} />,
      className: "min-w-0",
    },
    {
      header: t("admin.queue.currentStage"),
      accessor: (r) =>
        r.agent_progress ? (
          <div className="flex flex-wrap gap-1 items-center">
            {Object.entries(r.agent_progress).map(([aid, info]) => (
              <span
                key={aid}
                role="status"
                aria-label={`${aid}: ${info.success ? "success" : "failed"}, ${info.duration_ms.toFixed(0)}ms`}
                className={`inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium ${
                  info.success
                    ? "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400"
                    : "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400"
                }`}
                title={`${info.duration_ms.toFixed(0)}ms · ${info.tokens_used} tokens${info.error ? ` · ${info.error}` : ""}`}
              >
                {aid}
              </span>
            ))}
            {r.current_agent && (
              <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400 animate-pulse">
                {r.current_agent}...
              </span>
            )}
          </div>
        ) : r.current_stage ? (
          <StatusBadge status={r.current_stage} />
        ) : (
          "-"
        ),
      className: "min-w-48 shrink-0",
    },
    {
      header: t("admin.queue.elapsed"),
      accessor: (r) => formatElapsed(r.started_at),
      className: "w-20 shrink-0 text-right",
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
      className: "w-20 shrink-0",
    },
    {
      header: t("admin.articleTitle", "Title"),
      accessor: (r) => <TitleCell title={r.title} />,
      className: "min-w-0",
    },
    {
      header: t("admin.status"),
      accessor: (r) => <StatusBadge status={r.status ?? "unknown"} />,
      className: "w-24 shrink-0",
    },
    {
      header: t("admin.duration"),
      accessor: (r) => formatDuration(r.duration_ms),
      className: "w-20 shrink-0 text-right",
    },
    {
      header: t("admin.errorDetail"),
      accessor: (r) =>
        r.error ? (
          <span
            className="block truncate text-xs text-red-600 dark:text-red-400"
            title={r.error}
          >
            {r.error}
          </span>
        ) : null,
      className: "w-40 shrink-0",
    },
  ];

  const queueTotalPages = paginatedQueue
    ? Math.max(1, Math.ceil(paginatedQueue.total / paginatedQueue.page_size))
    : 1;

  const recentTotalPages = paginatedRecent
    ? Math.max(1, Math.ceil(paginatedRecent.total / paginatedRecent.page_size))
    : 1;

  return (
    <div className="flex flex-col gap-4">
      {/* Paused banner */}
      {queue.paused && (
        <div className="flex items-center gap-2 rounded-md bg-amber-50 p-3 text-sm text-amber-700 dark:bg-amber-900/20 dark:text-amber-400">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          {t("admin.queue.pausedBanner")}
        </div>
      )}

      {/* Circuit breaker banner — per-purpose */}
      {queue.circuitBreaker?.state === "open" && (
        <div className="space-y-2 rounded-md bg-red-50 p-3 text-sm text-red-700 dark:bg-red-900/20 dark:text-red-400">
          <div className="flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 shrink-0" />
            <span className="flex-1">
              {t("admin.queue.circuitBreakerOpen", {
                defaultValue:
                  "Circuit breaker OPEN — pipeline paused. Failing purposes: {{purposes}}",
                purposes:
                  (queue.circuitBreaker.openPurposes ?? []).join(", ") ||
                  "unknown",
              })}
            </span>
            <button
              onClick={() => resetCBMutation.mutate(undefined)}
              disabled={resetCBMutation.isPending}
              className="shrink-0 rounded bg-red-600 px-3 py-1 text-xs font-medium text-white hover:bg-red-700 disabled:opacity-50 dark:bg-red-700 dark:hover:bg-red-600"
            >
              {resetCBMutation.isPending
                ? t("common.resetting", "Resetting...")
                : t("admin.queue.resetAll", "Reset all")}
            </button>
          </div>
          {queue.circuitBreaker.purposes &&
            queue.circuitBreaker.purposes.length > 0 && (
              <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-3 md:grid-cols-4">
                {queue.circuitBreaker.purposes.map((p) => (
                  <div
                    key={p.purpose}
                    className={`flex items-center justify-between rounded border px-2 py-1 ${
                      p.state === "open"
                        ? "border-red-300 bg-red-100/60 dark:border-red-700 dark:bg-red-900/40"
                        : "border-emerald-300 bg-emerald-50 text-emerald-700 dark:border-emerald-700 dark:bg-emerald-900/20 dark:text-emerald-400"
                    }`}
                  >
                    <span className="truncate font-mono">{p.purpose}</span>
                    <span className="ml-2 shrink-0">
                      {p.state === "open"
                        ? `✗ ${p.consecutiveFailures}`
                        : "✓"}
                    </span>
                    {p.state === "open" && (
                      <button
                        onClick={() => resetCBMutation.mutate(p.purpose)}
                        disabled={resetCBMutation.isPending}
                        className="ml-2 shrink-0 rounded bg-red-600 px-2 py-0.5 text-[10px] font-medium text-white hover:bg-red-700 disabled:opacity-50 dark:bg-red-700 dark:hover:bg-red-600"
                      >
                        {t("common.reset", "Reset")}
                      </button>
                    )}
                  </div>
                ))}
              </div>
            )}
        </div>
      )}

      {/* Stats row */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatsCard
          label={t("admin.queue.queued")}
          value={queue.counts.queued}
          {...(queue.counts.queued_high != null ||
          queue.counts.queued_low != null
            ? {
                subtitle: `H: ${queue.counts.queued_high ?? 0} / L: ${queue.counts.queued_low ?? 0}`,
              }
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
            {t("admin.queue.active")} {queue.concurrency.active} /{" "}
            {t("admin.queue.target")} {queue.concurrency.target}
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
            {t("admin.queue.queued")} ({queue.counts.queued.toLocaleString()})
          </Tabs.Trigger>
          <Tabs.Trigger value="processing" className={tabTriggerClass}>
            {t("admin.queue.processing")} ({queue.counts.processing})
          </Tabs.Trigger>
          <Tabs.Trigger value="recent" className={tabTriggerClass}>
            {t("admin.queue.recent")} ({paginatedRecent?.total ?? queue.recent.length})
          </Tabs.Trigger>
        </Tabs.List>

        {/* Queued tab */}
        <Tabs.Content value="queued">
          <div className="mt-3 flex flex-col gap-3">
            {paginatedQueue && (
              <Pagination
                page={queuePage}
                totalPages={queueTotalPages}
                pageSize={queuePageSize}
                onPageChange={setQueuePage}
                onPageSizeChange={handleQueuePageSizeChange}
                t={t}
              />
            )}
            <div className="rounded-lg border border-border bg-card">
              <DataTable
                columns={queuedColumns}
                data={paginatedQueue?.items ?? queue.queued}
                keyExtractor={(r) => r.article_id}
                emptyMessage={t("admin.queue.noItems")}
                className="table-fixed"
              />
            </div>
          </div>
        </Tabs.Content>

        {/* Processing tab */}
        <Tabs.Content value="processing">
          <div className="mt-3 rounded-lg border border-border bg-card">
            <DataTable
              columns={processingColumns}
              data={queue.processing}
              keyExtractor={(r) => r.article_id}
              emptyMessage={t("admin.queue.noItems")}
              className="table-fixed"
            />
          </div>
        </Tabs.Content>

        {/* Recent tab */}
        <Tabs.Content value="recent">
          <div className="mt-3 flex flex-col gap-3">
            {paginatedRecent && (
              <Pagination
                page={recentPage}
                totalPages={recentTotalPages}
                pageSize={recentPageSize}
                onPageChange={setRecentPage}
                onPageSizeChange={handleRecentPageSizeChange}
                t={t}
              />
            )}
            <div className="rounded-lg border border-border bg-card">
              <DataTable
                columns={recentColumns}
                data={paginatedRecent?.items ?? queue.recent}
                keyExtractor={(r) => r.article_id + (r.completed_at ?? "")}
                emptyMessage={t("admin.queue.noItems")}
                className="table-fixed"
              />
            </div>
          </div>
        </Tabs.Content>
      </Tabs.Root>
    </div>
  );
}

/* ---------- Pipeline Events (existing) ---------- */

/* Stage display names */
const STAGE_LABELS: Record<string, string> = {
  fetch: "抓取",
  clean: "清洗",
  embedding: "向量化",
  semantic_dedup: "语义去重",
  classify: "分类",
  "agent:summarizer": "摘要",
  "agent:translator": "翻译",
  "agent:entity": "实体",
  "agent:finance_analyzer": "金融分析",
  // Legacy agent names
  "agent:embedder": "嵌入",
  "agent:sentiment": "情感",
  "agent:tagger": "标签",
  "agent:deep_reporter": "深度报告",
  "agent:impact_scorer": "打分",
};

function stageLabel(stage: string): string {
  return STAGE_LABELS[stage] ?? stage.replace("agent:", "");
}

/* Hidden internal events */
const HIDDEN_STAGES = new Set(["p2_complete", "p1_complete"]);

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

  const filtered = (events ?? []).filter((e) => {
    if (HIDDEN_STAGES.has(e.stage)) return false;
    if (statusFilter !== "all" && e.status !== statusFilter) return false;
    return true;
  });

  const eventColumns: Column<PipelineEventRaw>[] = [
    {
      header: t("admin.stage"),
      accessor: (r) => (
        <span className="inline-flex items-center gap-1.5">
          <span
            className={`inline-block h-2 w-2 rounded-full ${
              r.stage.startsWith("agent:") ? "bg-blue-500" : "bg-amber-500"
            }`}
          />
          {stageLabel(r.stage)}
        </span>
      ),
    },
    {
      header: t("admin.status"),
      accessor: (r) => <StatusBadge status={r.status} />,
    },
    {
      header: t("admin.duration"),
      accessor: (r) => formatDuration(r.duration_ms),
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
            className="block truncate text-xs text-red-600 dark:text-red-400"
            title={r.error}
          >
            {r.error}
          </span>
        ) : null,
    },
  ];

  const selectClass =
    "rounded-md border border-border bg-background px-3 py-1.5 text-sm text-foreground outline-none focus:border-primary";

  return (
    <div className="flex flex-col gap-4">
      {/* Filters */}
      <div className="flex flex-wrap gap-3">
        <select
          value={stageFilter}
          onChange={(e) => setStageFilter(e.target.value)}
          className={selectClass}
        >
          <option value="all">{t("admin.allStages")}</option>
          <optgroup label="Pipeline">
            <option value="fetch">抓取 (fetch)</option>
            <option value="clean">清洗 (clean)</option>
            <option value="embedding">向量化 (embedding)</option>
            <option value="semantic_dedup">语义去重 (semantic_dedup)</option>
            <option value="classify">分类 (classify)</option>
          </optgroup>
          <optgroup label="Agents">
            <option value="agent:summarizer">摘要</option>
            <option value="agent:translator">翻译</option>
            <option value="agent:entity">实体</option>
            <option value="agent:finance_analyzer">金融分析</option>
          </optgroup>
        </select>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className={selectClass}
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
        <>
          {/* Desktop: table */}
          <div className="hidden rounded-lg border border-border bg-card sm:block">
            <DataTable
              columns={eventColumns}
              data={filtered}
              keyExtractor={(r) => r.id}
              emptyMessage={t("admin.noEvents")}
            />
          </div>

          {/* Mobile: cards */}
          <div className="flex flex-col gap-2 sm:hidden">
            {filtered.length === 0 ? (
              <div className="py-8 text-center text-sm text-muted-foreground">
                {t("admin.noEvents")}
              </div>
            ) : (
              filtered.map((e) => (
                <div
                  key={e.id}
                  className="rounded-lg border border-border bg-card p-3"
                >
                  <div className="flex items-center justify-between">
                    <span className="inline-flex items-center gap-1.5 text-sm font-medium">
                      <span
                        className={`inline-block h-2 w-2 rounded-full ${
                          e.stage.startsWith("agent:")
                            ? "bg-blue-500"
                            : "bg-amber-500"
                        }`}
                      />
                      {stageLabel(e.stage)}
                    </span>
                    <StatusBadge status={e.status} />
                  </div>
                  <div className="mt-2 flex items-center justify-between text-xs text-muted-foreground">
                    <span className="font-mono">
                      {e.article_id?.slice(0, 8) ?? "-"}
                    </span>
                    <span>{formatDuration(e.duration_ms)}</span>
                    <span>
                      {new Date(e.created_at).toLocaleString([], {
                        hour: "2-digit",
                        minute: "2-digit",
                      })}
                    </span>
                  </div>
                  {e.error && (
                    <div className="mt-1.5 truncate text-xs text-red-600 dark:text-red-400">
                      {e.error}
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        </>
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
