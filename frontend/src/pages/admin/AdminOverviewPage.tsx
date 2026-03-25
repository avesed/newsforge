import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import {
  Newspaper,
  CalendarDays,
  Zap,
  Users,
  Key,
  Inbox,
  Loader2,
  CircleAlert,
} from "lucide-react";
import { getDashboardStats, getLLMProviders } from "@/api/admin";
import { StatsCard } from "@/components/admin/StatsCard";
import { BarChart } from "@/components/admin/BarChart";
import { DataTable, type Column } from "@/components/admin/DataTable";
import { StatusBadge } from "@/components/admin/StatusBadge";
import { AdminLayout } from "@/components/admin/AdminLayout";
import { CATEGORY_COLORS, type CategorySlug } from "@/types";

// Entity table columns
const entityColumns: Column<{ entity: string; type: string; mention_count: number }>[] = [
  { header: "Entity", accessor: (r) => r.entity },
  {
    header: "Type",
    accessor: (r) => (
      <StatusBadge status={r.type ?? "unknown"} />
    ),
  },
  {
    header: "Mentions",
    accessor: (r) => r.mention_count,
    className: "text-right",
  },
];

function SentimentBar({
  label,
  count,
  total,
  color,
}: {
  label: string;
  count: number;
  total: number;
  color: string;
}) {
  const pct = Math.round((count / total) * 100);
  return (
    <div className="flex items-center gap-3">
      <span className="w-16 shrink-0 text-sm text-muted-foreground">
        {label}
      </span>
      <div className="relative h-4 flex-1 overflow-hidden rounded-full bg-muted">
        <div
          className={`absolute inset-y-0 left-0 rounded-full ${color}`}
          style={{ width: `${pct}%`, minWidth: count > 0 ? "4px" : "0px" }}
        />
      </div>
      <span className="w-16 shrink-0 text-right text-sm text-foreground">
        {count} ({pct}%)
      </span>
    </div>
  );
}

function OverviewContent() {
  const { t } = useTranslation();

  const { data: stats, isLoading } = useQuery({
    queryKey: ["admin", "dashboard"],
    queryFn: getDashboardStats,
    refetchInterval: 15_000,
  });

  const { data: providers } = useQuery({
    queryKey: ["admin", "llm-providers"],
    queryFn: getLLMProviders,
  });

  if (isLoading || !stats) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const o = stats.overview;

  // Category chart data
  const catData = Object.entries(stats.category_distribution)
    .sort(([, a], [, b]) => b - a)
    .map(([slug, count]) => ({
      label: slug,
      value: count,
      color: CATEGORY_COLORS[slug as CategorySlug] ?? "#6b7280",
    }));

  // Hourly chart data (last 24h)
  const hourlyData = stats.hourly_counts.map((h) => ({
    label: new Date(h.hour).toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
    }),
    value: h.count,
  }));

  // Sentiment totals
  const sentTotal =
    stats.sentiment_distribution.positive +
    stats.sentiment_distribution.neutral +
    stats.sentiment_distribution.negative || 1;

  return (
    <div className="flex flex-col gap-6">
      {/* LLM not configured banner */}
      {providers !== undefined && providers.length === 0 && (
        <div className="flex items-center gap-3 rounded-lg border-2 border-amber-400 bg-amber-50 p-4 dark:border-amber-600 dark:bg-amber-900/20">
          <CircleAlert className="h-5 w-5 shrink-0 text-amber-600 dark:text-amber-400" />
          <p className="text-sm font-medium text-amber-800 dark:text-amber-300">
            {t("admin.configureLlmBanner")}
          </p>
        </div>
      )}

      {/* KPI Cards */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <StatsCard
          label={t("admin.totalArticles")}
          value={o.articles_total.toLocaleString()}
          icon={Newspaper}
        />
        <StatsCard
          label={t("admin.articlesToday")}
          value={o.articles_today.toLocaleString()}
          icon={CalendarDays}
        />
        <StatsCard
          label={t("admin.activeEvents")}
          value={o.events_active.toLocaleString()}
          icon={Zap}
        />
        <StatsCard
          label={t("admin.users")}
          value={o.users_total.toLocaleString()}
          icon={Users}
        />
        <StatsCard
          label={t("admin.apiConsumers")}
          value={o.consumers_active.toLocaleString()}
          icon={Key}
        />
        <StatsCard
          label={t("admin.queueDepth")}
          value={stats.queue.main + stats.queue.retry}
          icon={Inbox}
        />
      </div>

      {/* Category Distribution */}
      <section className="rounded-lg border border-border bg-card p-5">
        <h3 className="mb-3 text-sm font-semibold text-foreground">
          {t("admin.categoryDistribution")}
        </h3>
        {catData.length > 0 ? (
          <BarChart data={catData} />
        ) : (
          <p className="text-sm text-muted-foreground">
            {t("admin.noData")}
          </p>
        )}
      </section>

      {/* Hourly Counts */}
      {hourlyData.length > 0 && (
        <section className="rounded-lg border border-border bg-card p-5">
          <h3 className="mb-3 text-sm font-semibold text-foreground">
            {t("admin.hourlyArticles")}
          </h3>
          <BarChart data={hourlyData} />
        </section>
      )}

      {/* Top Entities + Sentiment side by side */}
      <div className="grid gap-4 lg:grid-cols-2">
        {/* Top Entities */}
        <section className="rounded-lg border border-border bg-card p-5">
          <h3 className="mb-3 text-sm font-semibold text-foreground">
            {t("admin.topEntities")}
          </h3>
          <DataTable
            columns={entityColumns}
            data={stats.top_entities}
            keyExtractor={(e) => `${e.entity}-${e.type}`}
            emptyMessage={t("admin.noData")}
          />
        </section>

        {/* Sentiment Distribution */}
        <section className="rounded-lg border border-border bg-card p-5">
          <h3 className="mb-3 text-sm font-semibold text-foreground">
            {t("admin.sentimentDistribution")}
          </h3>
          <div className="flex flex-col gap-3 mt-2">
            <SentimentBar
              label={t("sentiment.positive")}
              count={stats.sentiment_distribution.positive}
              total={sentTotal}
              color="bg-green-500"
            />
            <SentimentBar
              label={t("sentiment.neutral")}
              count={stats.sentiment_distribution.neutral}
              total={sentTotal}
              color="bg-gray-400"
            />
            <SentimentBar
              label={t("sentiment.negative")}
              count={stats.sentiment_distribution.negative}
              total={sentTotal}
              color="bg-red-500"
            />
          </div>

          {/* Pipeline Performance Summary */}
          <div className="mt-6 border-t border-border pt-4">
            <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              {t("admin.pipelinePerformance")}
            </h4>
            <div className="grid grid-cols-2 gap-3 text-sm">
              <div>
                <span className="text-muted-foreground">
                  {t("admin.successRate")}
                </span>
                <p className="font-medium text-foreground">
                  {(stats.pipeline_performance.success_rate * 100).toFixed(1)}%
                </p>
              </div>
              <div>
                <span className="text-muted-foreground">
                  {t("admin.avgDuration")}
                </span>
                <p className="font-medium text-foreground">
                  {stats.pipeline_performance.avg_duration_ms.toFixed(0)}ms
                </p>
              </div>
              <div>
                <span className="text-muted-foreground">
                  {t("admin.events24h")}
                </span>
                <p className="font-medium text-foreground">
                  {stats.pipeline_performance.events_last_24h}
                </p>
              </div>
              <div>
                <span className="text-muted-foreground">
                  {t("admin.errors24h")}
                </span>
                <p className="font-medium text-foreground">
                  {stats.pipeline_performance.error_count_24h}
                </p>
              </div>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}

export default function AdminOverviewPage() {
  return (
    <AdminLayout>
      <OverviewContent />
    </AdminLayout>
  );
}
