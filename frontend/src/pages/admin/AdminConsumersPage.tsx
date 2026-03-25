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
} from "lucide-react";
import {
  getConsumers,
  createConsumer,
  deleteConsumer,
} from "@/api/admin";
import type { ConsumerRaw, ConsumerCreateRaw } from "@/api/admin";
import { getErrorMessage } from "@/api/client";
import { StatusBadge } from "@/components/admin/StatusBadge";
import { DataTable, type Column } from "@/components/admin/DataTable";
import { AdminLayout } from "@/components/admin/AdminLayout";

function ConsumersContent() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [formName, setFormName] = useState("");
  const [formDesc, setFormDesc] = useState("");
  const [error, setError] = useState("");
  const [newKey, setNewKey] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

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
      await navigator.clipboard.writeText(newKey);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const consumerColumns: Column<ConsumerRaw>[] = [
    { header: t("admin.consumerName"), accessor: (r) => r.name },
    {
      header: t("admin.keyPrefix"),
      accessor: (r) => (
        <code className="rounded bg-muted px-1.5 py-0.5 text-xs">
          {r.apiKeyPrefix}...
        </code>
      ),
    },
    {
      header: t("admin.rateLimit"),
      accessor: (r) => `${r.rateLimit}/min`,
      className: "text-right",
    },
    {
      header: t("admin.status"),
      accessor: (r) => (
        <StatusBadge status={r.isActive ? "active" : "inactive"} />
      ),
    },
    {
      header: t("admin.lastUsed"),
      accessor: (r) =>
        r.lastUsedAt
          ? new Date(r.lastUsedAt).toLocaleDateString()
          : "-",
    },
    {
      header: "",
      accessor: (r) =>
        r.isActive ? (
          <button
            onClick={() => deleteMutation.mutate(r.id)}
            disabled={deleteMutation.isPending}
            className="rounded p-1.5 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        ) : null,
    },
  ];

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
            <code className="flex-1 break-all rounded bg-white px-3 py-2 text-sm font-mono text-foreground dark:bg-gray-900">
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
        <DataTable
          columns={consumerColumns}
          data={consumers ?? []}
          keyExtractor={(r) => r.id}
          emptyMessage={t("admin.noConsumers")}
        />
      </div>
    </div>
  );
}

export default function AdminConsumersPage() {
  return (
    <AdminLayout>
      <ConsumersContent />
    </AdminLayout>
  );
}
