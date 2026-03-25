import { useState, useEffect, useCallback, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Loader2,
  Plus,
  Trash2,
  Pencil,
  Power,
  FlaskConical,
  Rss,
  Clock,
  Radio,
  CheckCircle2,
} from "lucide-react";
import {
  getSources,
  updateSource,
  deleteSource,
  createSource,
  getAllFeeds,
  createAdminFeed,
  updateAdminFeed,
  deleteAdminFeed,
  testAdminFeed,
  getGoogleNewsOptions,
  buildGoogleNewsUrl,
} from "@/api/admin";
import type { AdminFeedRaw } from "@/api/admin";
import { getErrorMessage } from "@/api/client";
import { StatusBadge } from "@/components/admin/StatusBadge";
import { AdminLayout } from "@/components/admin/AdminLayout";
import { INPUT_CLASS, timeAgo } from "@/components/admin/utils";
import { ALL_CATEGORIES, CATEGORY_COLORS, type CategorySlug } from "@/types";

// ---------------------------------------------------------------------------
// Add Feed Section (Google News wizard + Custom RSS)
// ---------------------------------------------------------------------------
type SourceType = "google_news" | "custom_rss";

function AddFeedSection({
  feeds,
}: {
  feeds: AdminFeedRaw[] | undefined;
}) {
  const { t, i18n } = useTranslation();
  const isZh = i18n.language.startsWith("zh");
  const queryClient = useQueryClient();

  // Source type toggle
  const [sourceType, setSourceType] = useState<SourceType>("google_news");

  // Google News state
  const [selectedTopic, setSelectedTopic] = useState("");
  const [selectedLocale, setSelectedLocale] = useState("");
  const [preview, setPreview] = useState<{
    url: string;
    title: string;
    category: string | null;
  } | null>(null);
  const [buildingUrl, setBuildingUrl] = useState(false);
  const [buildError, setBuildError] = useState("");

  // Custom RSS state
  const [customUrl, setCustomUrl] = useState("");
  const [customTitle, setCustomTitle] = useState("");
  const [customCategory, setCustomCategory] = useState("");
  const [customInterval, setCustomInterval] = useState(15);

  // Shared
  const [createError, setCreateError] = useState("");

  const existingUrls = new Set((feeds ?? []).map((f) => f.url));

  // Fetch Google News options from backend
  const { data: gnOptions } = useQuery({
    queryKey: ["admin", "google-news-options"],
    queryFn: getGoogleNewsOptions,
    staleTime: 10 * 60 * 1000,
  });

  // Build URL when topic + locale are both selected
  const doBuildUrl = useCallback(
    async (topic: string, locale: string) => {
      if (!topic || !locale) {
        setPreview(null);
        return;
      }
      setBuildingUrl(true);
      setBuildError("");
      try {
        const result = await buildGoogleNewsUrl(topic, locale);
        setPreview(result);
      } catch (err) {
        setBuildError(getErrorMessage(err));
        setPreview(null);
      } finally {
        setBuildingUrl(false);
      }
    },
    [],
  );

  useEffect(() => {
    if (sourceType === "google_news" && selectedTopic && selectedLocale) {
      void doBuildUrl(selectedTopic, selectedLocale);
    } else {
      setPreview(null);
    }
  }, [sourceType, selectedTopic, selectedLocale, doBuildUrl]);

  const createMutation = useMutation({
    mutationFn: createAdminFeed,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["admin", "feeds"] });
      setCreateError("");
      // Reset form after success
      if (sourceType === "google_news") {
        setSelectedTopic("");
        setSelectedLocale("");
        setPreview(null);
      } else {
        setCustomUrl("");
        setCustomTitle("");
        setCustomCategory("");
        setCustomInterval(15);
      }
    },
    onError: (err) => setCreateError(getErrorMessage(err)),
  });

  const handleGoogleNewsSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!preview) return;
    createMutation.mutate({
      url: preview.url,
      title: preview.title,
      feedType: "native_rss",
      categorySlug: preview.category ?? undefined,
      pollIntervalMinutes: 15,
      fulltextMode: false,
    });
  };

  const handleCustomRssSubmit = (e: FormEvent) => {
    e.preventDefault();
    createMutation.mutate({
      url: customUrl,
      title: customTitle || undefined,
      feedType: "native_rss",
      categorySlug: customCategory || undefined,
      pollIntervalMinutes: customInterval,
      fulltextMode: false,
    });
  };

  const isDuplicate = preview != null && existingUrls.has(preview.url);

  return (
    <section className="rounded-lg border border-border bg-card p-5">
      <h3 className="mb-4 flex items-center gap-2 text-sm font-semibold text-foreground">
        <Plus className="h-4 w-4 text-primary" />
        {t("admin.addFeed")}
      </h3>

      {createError && (
        <div className="mb-4 rounded-md bg-destructive/10 p-3 text-sm text-destructive">
          {createError}
        </div>
      )}

      {/* Source type selector */}
      <div className="mb-4 flex flex-col gap-1">
        <label className="text-xs text-muted-foreground">
          {t("admin.sourceType")}
        </label>
        <select
          value={sourceType}
          onChange={(e) => {
            setSourceType(e.target.value as SourceType);
            setCreateError("");
          }}
          className={INPUT_CLASS}
        >
          <option value="google_news">{t("admin.googleNewsRss")}</option>
          <option value="custom_rss">{t("admin.customRss")}</option>
        </select>
      </div>

      {/* Google News wizard */}
      {sourceType === "google_news" && (
        <form onSubmit={handleGoogleNewsSubmit} className="flex flex-col gap-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="flex flex-col gap-1">
              <label className="text-xs text-muted-foreground">
                {t("admin.topic")}
              </label>
              <select
                value={selectedTopic}
                onChange={(e) => setSelectedTopic(e.target.value)}
                className={INPUT_CLASS}
              >
                <option value="" disabled hidden>{t("admin.selectTopic")}</option>
                {(gnOptions?.topics ?? []).map((topic) => (
                  <option key={topic.id} value={topic.id}>
                    {isZh ? topic.labelZh : topic.labelEn}
                  </option>
                ))}
              </select>
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-xs text-muted-foreground">
                {t("admin.region")}
              </label>
              <select
                value={selectedLocale}
                onChange={(e) => setSelectedLocale(e.target.value)}
                className={INPUT_CLASS}
              >
                <option value="" disabled hidden>{t("admin.selectRegion")}</option>
                {(gnOptions?.locales ?? []).map((locale) => (
                  <option key={locale.id} value={locale.id}>
                    {isZh ? locale.labelZh : locale.labelEn}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Loading indicator */}
          {buildingUrl && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              {t("common.loading")}
            </div>
          )}

          {/* Build error */}
          {buildError && (
            <div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
              {buildError}
            </div>
          )}

          {/* Preview */}
          {preview != null && !buildingUrl && (
            <div className="rounded-lg bg-muted/30 p-4">
              <div className="mb-2 flex items-center gap-2">
                <span className="text-xs font-medium text-muted-foreground">
                  {t("admin.preview")}:
                </span>
                <span className="text-sm font-medium text-foreground">
                  {preview.title}
                </span>
                {isDuplicate && (
                  <span className="flex items-center gap-1 rounded-full bg-emerald-500/10 px-2 py-0.5 text-xs font-medium text-emerald-600 dark:text-emerald-400">
                    <CheckCircle2 className="h-3 w-3" />
                    {t("admin.alreadyAdded")}
                  </span>
                )}
              </div>
              <div className="flex items-start gap-2">
                <span className="shrink-0 text-xs font-medium text-muted-foreground">
                  {t("admin.previewUrl")}:
                </span>
                <span className="break-all text-xs text-muted-foreground">
                  {preview.url}
                </span>
              </div>
            </div>
          )}

          <button
            type="submit"
            disabled={
              !preview ||
              isDuplicate ||
              buildingUrl ||
              createMutation.isPending
            }
            className="flex w-fit items-center justify-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
          >
            {createMutation.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Plus className="h-4 w-4" />
            )}
            {t("admin.addFeed")}
          </button>
        </form>
      )}

      {/* Custom RSS form */}
      {sourceType === "custom_rss" && (
        <form onSubmit={handleCustomRssSubmit} className="flex flex-col gap-4">
          <div className="flex flex-col gap-1">
            <label className="text-xs text-muted-foreground">
              {t("admin.feedRssUrl")}
            </label>
            <input
              type="url"
              value={customUrl}
              onChange={(e) => setCustomUrl(e.target.value)}
              placeholder="https://example.com/rss"
              required
              className={INPUT_CLASS}
            />
          </div>

          <div className="flex flex-col gap-1">
            <label className="text-xs text-muted-foreground">
              {t("admin.feedTitle")}
            </label>
            <input
              type="text"
              value={customTitle}
              onChange={(e) => setCustomTitle(e.target.value)}
              placeholder={t("admin.feedTitle")}
              className={INPUT_CLASS}
            />
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="flex flex-col gap-1">
              <label className="text-xs text-muted-foreground">
                {t("admin.feedCategory")}
              </label>
              <select
                value={customCategory}
                onChange={(e) => setCustomCategory(e.target.value)}
                className={INPUT_CLASS}
              >
                <option value="">{t("admin.allCategories")}</option>
                {ALL_CATEGORIES.map((cat) => (
                  <option key={cat.slug} value={cat.slug}>
                    {isZh ? cat.nameZh : cat.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-xs text-muted-foreground">
                {t("admin.pollInterval")}
              </label>
              <div className="flex items-center gap-2">
                <input
                  type="number"
                  min={5}
                  max={1440}
                  value={customInterval}
                  onChange={(e) => setCustomInterval(Number(e.target.value))}
                  className={`${INPUT_CLASS} w-20`}
                />
                <span className="text-xs text-muted-foreground">
                  {t("admin.pollIntervalUnit")}
                </span>
              </div>
            </div>
          </div>

          <button
            type="submit"
            disabled={createMutation.isPending}
            className="flex w-fit items-center justify-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
          >
            {createMutation.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Plus className="h-4 w-4" />
            )}
            {t("admin.addFeed")}
          </button>
        </form>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// RSS Feeds Section
// ---------------------------------------------------------------------------
function RssFeedsSection({
  feeds,
  isLoading,
}: {
  feeds: AdminFeedRaw[] | undefined;
  isLoading: boolean;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  // Edit state
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [editCategory, setEditCategory] = useState("");
  const [editInterval, setEditInterval] = useState(15);
  const [editFulltext, setEditFulltext] = useState(false);

  // Delete confirm
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  // Test results
  const [testingId, setTestingId] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<
    Record<string, { success: boolean; message: string; articleCount: number }>
  >({});

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Parameters<typeof updateAdminFeed>[1] }) =>
      updateAdminFeed(id, data),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["admin", "feeds"] });
      setEditingId(null);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: deleteAdminFeed,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["admin", "feeds"] });
      setConfirmDeleteId(null);
    },
  });

  const toggleMutation = useMutation({
    mutationFn: ({ id, isEnabled }: { id: string; isEnabled: boolean }) =>
      updateAdminFeed(id, { isEnabled }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["admin", "feeds"] });
    },
  });

  const handleTest = async (id: string) => {
    setTestingId(id);
    try {
      const result = await testAdminFeed(id);
      setTestResults((prev) => ({ ...prev, [id]: result }));
    } catch (err) {
      setTestResults((prev) => ({
        ...prev,
        [id]: { success: false, message: getErrorMessage(err), articleCount: 0 },
      }));
    } finally {
      setTestingId(null);
    }
  };

  const startEdit = (feed: AdminFeedRaw) => {
    setEditingId(feed.id);
    setEditTitle(feed.title ?? "");
    setEditCategory(feed.categorySlug ?? "");
    setEditInterval(feed.pollIntervalMinutes);
    setEditFulltext(feed.fulltextMode);
  };

  const handleEditSave = (id: string) => {
    updateMutation.mutate({
      id,
      data: {
        title: editTitle || undefined,
        categorySlug: editCategory || undefined,
        pollIntervalMinutes: editInterval,
        fulltextMode: editFulltext,
      },
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
    <section>
      <div className="mb-4">
        <h3 className="text-sm font-semibold text-foreground">
          RSS {t("admin.feeds")}
        </h3>
      </div>

      {/* Empty state */}
      {(feeds == null || feeds.length === 0) && (
        <div className="flex flex-col items-center gap-3 rounded-lg border-2 border-dashed border-border py-12">
          <Rss className="h-10 w-10 text-muted-foreground" />
          <p className="text-sm font-medium text-muted-foreground">
            {t("admin.noFeeds")}
          </p>
        </div>
      )}

      {/* Feed cards */}
      <div className="flex flex-col gap-4">
        {(feeds ?? []).map((feed) => (
          <div
            key={feed.id}
            className="rounded-lg border border-border bg-card p-4"
          >
            {editingId === feed.id ? (
              /* Inline edit form */
              <div className="flex flex-col gap-3">
                <h4 className="text-sm font-semibold text-foreground">
                  {t("admin.editFeed")}
                </h4>
                <div className="flex flex-col gap-1">
                  <label className="text-xs text-muted-foreground">
                    {t("admin.feedTitle")}
                  </label>
                  <input
                    type="text"
                    value={editTitle}
                    onChange={(e) => setEditTitle(e.target.value)}
                    className={INPUT_CLASS}
                  />
                </div>
                <div className="grid gap-3 sm:grid-cols-3">
                  <div className="flex flex-col gap-1">
                    <label className="text-xs text-muted-foreground">
                      {t("admin.feedCategory")}
                    </label>
                    <select
                      value={editCategory}
                      onChange={(e) => setEditCategory(e.target.value)}
                      className={INPUT_CLASS}
                    >
                      <option value="">{t("admin.allCategories")}</option>
                      {ALL_CATEGORIES.map((cat) => (
                        <option key={cat.slug} value={cat.slug}>
                          {cat.nameZh}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="flex flex-col gap-1">
                    <label className="text-xs text-muted-foreground">
                      {t("admin.pollInterval")}
                    </label>
                    <div className="flex items-center gap-2">
                      <input
                        type="number"
                        min={5}
                        max={1440}
                        value={editInterval}
                        onChange={(e) => setEditInterval(Number(e.target.value))}
                        className={`${INPUT_CLASS} w-20`}
                      />
                      <span className="text-xs text-muted-foreground">
                        {t("admin.pollIntervalUnit")}
                      </span>
                    </div>
                  </div>
                  <label className="flex items-center gap-2 self-end py-2 text-sm text-foreground">
                    <input
                      type="checkbox"
                      checked={editFulltext}
                      onChange={(e) => setEditFulltext(e.target.checked)}
                      className="rounded border-border"
                    />
                    {t("admin.fulltextMode")}
                  </label>
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={() => handleEditSave(feed.id)}
                    disabled={updateMutation.isPending}
                    className="flex items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
                  >
                    {updateMutation.isPending ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      t("common.save")
                    )}
                  </button>
                  <button
                    onClick={() => setEditingId(null)}
                    className="rounded-md border border-border px-4 py-2 text-sm text-foreground hover:bg-accent"
                  >
                    {t("common.cancel")}
                  </button>
                </div>
              </div>
            ) : (
              /* Feed card display */
              <>
                {/* Header */}
                <div className="mb-2 flex items-start justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <Rss className="h-4 w-4 shrink-0 text-muted-foreground" />
                      <span className="font-semibold text-foreground">
                        {feed.title ?? feed.url}
                      </span>
                    </div>
                    {feed.title && (
                      <p
                        className="mt-0.5 truncate pl-6 text-xs text-muted-foreground"
                        title={feed.url}
                      >
                        {feed.url}
                      </p>
                    )}
                  </div>
                  <button
                    onClick={() =>
                      toggleMutation.mutate({
                        id: feed.id,
                        isEnabled: !feed.isEnabled,
                      })
                    }
                    disabled={toggleMutation.isPending}
                    className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full transition-colors ${
                      feed.isEnabled
                        ? "bg-green-500"
                        : "bg-gray-300 dark:bg-gray-600"
                    }`}
                  >
                    <span
                      className={`inline-block h-3.5 w-3.5 rounded-full bg-white transition-transform ${
                        feed.isEnabled ? "translate-x-[18px]" : "translate-x-0.5"
                      }`}
                    />
                  </button>
                </div>

                {/* Info badges row */}
                <div className="mb-3 flex flex-wrap items-center gap-2 text-xs">
                  <span className="rounded-full bg-blue-100 px-2 py-0.5 font-medium text-blue-700 dark:bg-blue-900/30 dark:text-blue-400">
                    {feed.feedType === "native_rss"
                      ? t("admin.nativeRss")
                      : t("admin.rsshub")}
                  </span>
                  {feed.categorySlug && (
                    <span
                      className="rounded-full px-2 py-0.5 font-medium"
                      style={{
                        backgroundColor:
                          (CATEGORY_COLORS[feed.categorySlug as CategorySlug] ??
                            "#6b7280") + "20",
                        color:
                          CATEGORY_COLORS[feed.categorySlug as CategorySlug] ??
                          "#6b7280",
                      }}
                    >
                      {feed.categorySlug}
                    </span>
                  )}
                  <span className="flex items-center gap-1 text-muted-foreground">
                    <Clock className="h-3 w-3" />
                    {feed.pollIntervalMinutes}
                    {t("admin.pollIntervalUnit")}
                  </span>
                  {feed.fulltextMode && (
                    <span className="rounded-full bg-green-100 px-2 py-0.5 font-medium text-green-700 dark:bg-green-900/30 dark:text-green-400">
                      Fulltext
                    </span>
                  )}
                  {feed.userId != null ? (
                    <span className="text-muted-foreground">
                      {t("admin.userFeed", { id: feed.userId })}
                    </span>
                  ) : (
                    <span className="text-muted-foreground">
                      {t("admin.systemFeed")}
                    </span>
                  )}
                </div>

                {/* Stats row */}
                <div className="mb-3 grid gap-x-6 gap-y-1 text-sm sm:grid-cols-3">
                  <div>
                    <span className="text-muted-foreground">
                      {t("admin.articleCount")}:{" "}
                    </span>
                    <span className="font-medium text-foreground">
                      {feed.articleCount}
                    </span>
                  </div>
                  <div>
                    <span className="text-muted-foreground">
                      {t("admin.lastPolled")}:{" "}
                    </span>
                    <span className="text-foreground">
                      {feed.lastPolledAt
                        ? timeAgo(feed.lastPolledAt)
                        : t("admin.neverPolled")}
                    </span>
                  </div>
                  <div>
                    <span className="text-muted-foreground">
                      {t("admin.errors")}:{" "}
                    </span>
                    <span
                      className={
                        feed.consecutiveErrors > 0
                          ? "font-medium text-red-600 dark:text-red-400"
                          : "text-foreground"
                      }
                    >
                      {feed.consecutiveErrors}
                    </span>
                  </div>
                </div>

                {/* Last error */}
                {feed.lastError && (
                  <div className="mb-3 rounded-md bg-red-50 p-2 text-xs text-red-700 dark:bg-red-900/20 dark:text-red-400">
                    {feed.lastError}
                  </div>
                )}

                {/* Test result inline */}
                {testResults[feed.id] != null && (
                  <div
                    className={`mb-3 rounded-md p-2 text-xs ${
                      testResults[feed.id]!.success
                        ? "bg-green-50 text-green-700 dark:bg-green-900/20 dark:text-green-400"
                        : "bg-red-50 text-red-700 dark:bg-red-900/20 dark:text-red-400"
                    }`}
                  >
                    {testResults[feed.id]!.success
                      ? t("admin.testFeedSuccess")
                      : t("admin.testFeedFail")}
                    {" -- "}
                    {testResults[feed.id]!.message}
                    {testResults[feed.id]!.success &&
                      testResults[feed.id]!.articleCount > 0 &&
                      ` (${t("admin.articlesFound", { count: testResults[feed.id]!.articleCount })})`}
                  </div>
                )}

                {/* Actions */}
                <div className="flex flex-wrap items-center gap-2">
                  <button
                    onClick={() => void handleTest(feed.id)}
                    disabled={testingId === feed.id}
                    className="flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1.5 text-xs font-medium text-foreground hover:bg-accent disabled:opacity-50"
                  >
                    {testingId === feed.id ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <FlaskConical className="h-3.5 w-3.5" />
                    )}
                    {testingId === feed.id
                      ? t("admin.testingFeed")
                      : t("admin.testFeed")}
                  </button>
                  <button
                    onClick={() => startEdit(feed)}
                    className="flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1.5 text-xs font-medium text-foreground hover:bg-accent"
                  >
                    <Pencil className="h-3.5 w-3.5" />
                    {t("admin.editFeed")}
                  </button>
                  <button
                    onClick={() =>
                      toggleMutation.mutate({
                        id: feed.id,
                        isEnabled: !feed.isEnabled,
                      })
                    }
                    disabled={toggleMutation.isPending}
                    className="flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1.5 text-xs font-medium text-foreground hover:bg-accent disabled:opacity-50"
                  >
                    <Power className="h-3.5 w-3.5" />
                    {feed.isEnabled ? t("feeds.disable") : t("feeds.enable")}
                  </button>
                  {confirmDeleteId === feed.id ? (
                    <div className="flex items-center gap-1">
                      <button
                        onClick={() => deleteMutation.mutate(feed.id)}
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
                      onClick={() => setConfirmDeleteId(feed.id)}
                      className="flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1.5 text-xs font-medium text-destructive hover:bg-destructive/10"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                      {t("common.delete")}
                    </button>
                  )}
                </div>
              </>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// API Sources Section
// ---------------------------------------------------------------------------
function ApiSourcesSection() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [formName, setFormName] = useState("");
  const [formType, setFormType] = useState("rss");
  const [formProvider, setFormProvider] = useState("custom");
  const [formCategories, setFormCategories] = useState<string[]>([]);
  const [formMarkets, setFormMarkets] = useState("");
  const [error, setError] = useState("");
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  const { data: sources, isLoading } = useQuery({
    queryKey: ["admin", "sources"],
    queryFn: getSources,
  });

  const toggleMutation = useMutation({
    mutationFn: ({ id, isEnabled }: { id: string; isEnabled: boolean }) =>
      updateSource(id, { isEnabled }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["admin", "sources"] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: deleteSource,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["admin", "sources"] });
      setConfirmDeleteId(null);
    },
  });

  const createMutation = useMutation({
    mutationFn: createSource,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["admin", "sources"] });
      setShowForm(false);
      setFormName("");
      setFormType("rss");
      setFormProvider("custom");
      setFormCategories([]);
      setFormMarkets("");
      setError("");
    },
    onError: (err) => setError(getErrorMessage(err)),
  });

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    const markets = formMarkets
      .split(",")
      .map((m) => m.trim())
      .filter(Boolean);
    createMutation.mutate({
      name: formName,
      sourceType: formType,
      provider: formProvider,
      config: {
        categories: formCategories.length > 0 ? formCategories : undefined,
        markets: markets.length > 0 ? markets : undefined,
      },
    });
  };

  const handleCategoryToggle = (slug: string) => {
    setFormCategories((prev) =>
      prev.includes(slug) ? prev.filter((c) => c !== slug) : [...prev, slug],
    );
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  // Only show this section if there are sources or the form is open
  if (!showForm && (sources == null || sources.length === 0)) {
    return null;
  }

  return (
    <section>
      <div className="mb-4 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-foreground">
          API \u6570\u636e\u6e90
        </h3>
        {!showForm && (
          <button
            onClick={() => setShowForm(true)}
            className="flex items-center gap-1.5 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground"
          >
            <Plus className="h-4 w-4" />
            {t("admin.addSource")}
          </button>
        )}
      </div>

      {showForm && (
        <form
          onSubmit={handleSubmit}
          className="mb-4 flex flex-col gap-3 rounded-lg border border-border bg-card p-4"
        >
          <h4 className="text-sm font-semibold text-foreground">
            {t("admin.addSource")}
          </h4>
          {error && (
            <div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
              {error}
            </div>
          )}
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="flex flex-col gap-1">
              <label className="text-xs text-muted-foreground">
                {t("admin.sourceName")}
              </label>
              <input
                type="text"
                value={formName}
                onChange={(e) => setFormName(e.target.value)}
                placeholder="Google News CN"
                required
                className={INPUT_CLASS}
              />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-xs text-muted-foreground">
                {t("admin.sourceType")}
              </label>
              <select
                value={formType}
                onChange={(e) => setFormType(e.target.value)}
                className={INPUT_CLASS}
              >
                <option value="rss">RSS</option>
                <option value="api">API</option>
                <option value="scraper">Scraper</option>
              </select>
            </div>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="flex flex-col gap-1">
              <label className="text-xs text-muted-foreground">
                {t("admin.provider")}
              </label>
              <input
                type="text"
                value={formProvider}
                onChange={(e) => setFormProvider(e.target.value)}
                placeholder="google_news"
                required
                className={INPUT_CLASS}
              />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-xs text-muted-foreground">
                {t("admin.sourceMarkets")}
              </label>
              <input
                type="text"
                value={formMarkets}
                onChange={(e) => setFormMarkets(e.target.value)}
                placeholder="us, cn, hk"
                className={INPUT_CLASS}
              />
            </div>
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs text-muted-foreground">
              {t("admin.sourceCategories")}
            </label>
            <div className="flex flex-wrap gap-2">
              {ALL_CATEGORIES.map((cat) => (
                <label
                  key={cat.slug}
                  className={`flex cursor-pointer items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium transition-colors ${
                    formCategories.includes(cat.slug)
                      ? "border-primary bg-primary/10 text-primary"
                      : "border-border text-muted-foreground hover:border-primary/50"
                  }`}
                >
                  <input
                    type="checkbox"
                    className="sr-only"
                    checked={formCategories.includes(cat.slug)}
                    onChange={() => handleCategoryToggle(cat.slug)}
                  />
                  {cat.nameZh}
                </label>
              ))}
            </div>
          </div>
          <div className="flex gap-2">
            <button
              type="submit"
              disabled={createMutation.isPending}
              className="flex items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
            >
              {createMutation.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                t("common.save")
              )}
            </button>
            <button
              type="button"
              onClick={() => {
                setShowForm(false);
                setError("");
              }}
              className="rounded-md border border-border px-4 py-2 text-sm text-foreground hover:bg-accent"
            >
              {t("common.cancel")}
            </button>
          </div>
        </form>
      )}

      {/* Source cards */}
      <div className="flex flex-col gap-4">
        {(sources ?? []).map((source) => (
          <div
            key={source.id}
            className="rounded-lg border border-border bg-card p-4"
          >
            {/* Header */}
            <div className="mb-3 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Radio className="h-4 w-4 text-muted-foreground" />
                <span className="font-semibold text-foreground">
                  {source.name}
                </span>
                <StatusBadge status={source.healthStatus} />
              </div>
              <button
                onClick={() =>
                  toggleMutation.mutate({
                    id: source.id,
                    isEnabled: !source.isEnabled,
                  })
                }
                disabled={toggleMutation.isPending}
                className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full transition-colors ${
                  source.isEnabled
                    ? "bg-green-500"
                    : "bg-gray-300 dark:bg-gray-600"
                }`}
              >
                <span
                  className={`inline-block h-3.5 w-3.5 rounded-full bg-white transition-transform ${
                    source.isEnabled ? "translate-x-[18px]" : "translate-x-0.5"
                  }`}
                />
              </button>
            </div>

            {/* Info grid */}
            <div className="mb-3 grid gap-x-6 gap-y-1.5 text-sm sm:grid-cols-2 lg:grid-cols-4">
              <div>
                <span className="text-muted-foreground">
                  {t("admin.sourceType")}:{" "}
                </span>
                <span className="text-foreground">{source.sourceType}</span>
              </div>
              <div>
                <span className="text-muted-foreground">
                  {t("admin.provider")}:{" "}
                </span>
                <span className="font-mono text-foreground">
                  {source.provider}
                </span>
              </div>
              <div>
                <span className="text-muted-foreground">
                  {t("admin.articleCount")}:{" "}
                </span>
                <span className="text-foreground">{source.articleCount}</span>
              </div>
              {source.consecutiveErrors > 0 && (
                <div>
                  <span className="text-muted-foreground">
                    {t("admin.errors")}:{" "}
                  </span>
                  <span className="text-red-600 dark:text-red-400">
                    {source.consecutiveErrors}
                  </span>
                </div>
              )}
            </div>

            {/* Category badges */}
            {source.categories != null && source.categories.length > 0 && (
              <div className="mb-3 flex flex-wrap gap-1.5">
                {source.categories.map((cat) => (
                  <span
                    key={cat}
                    className="rounded-full px-2 py-0.5 text-xs font-medium"
                    style={{
                      backgroundColor:
                        (CATEGORY_COLORS[cat as CategorySlug] ?? "#6b7280") + "20",
                      color: CATEGORY_COLORS[cat as CategorySlug] ?? "#6b7280",
                    }}
                  >
                    {cat}
                  </span>
                ))}
              </div>
            )}

            {/* Market badges */}
            {source.markets != null && source.markets.length > 0 && (
              <div className="mb-3 flex flex-wrap gap-1.5">
                {source.markets.map((m) => (
                  <span
                    key={m}
                    className="rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-700 dark:bg-blue-900/30 dark:text-blue-400"
                  >
                    {m.toUpperCase()}
                  </span>
                ))}
              </div>
            )}

            {/* Actions */}
            <div className="flex flex-wrap items-center gap-2">
              {confirmDeleteId === source.id ? (
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => deleteMutation.mutate(source.id)}
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
                  onClick={() => setConfirmDeleteId(source.id)}
                  className="flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1.5 text-xs font-medium text-destructive hover:bg-destructive/10"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                  {t("common.delete")}
                </button>
              )}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Main Feeds Page
// ---------------------------------------------------------------------------
function FeedsContent() {
  const { t } = useTranslation();
  const { data: feeds, isLoading } = useQuery({
    queryKey: ["admin", "feeds"],
    queryFn: getAllFeeds,
    refetchInterval: 30_000,
  });

  return (
    <div className="flex flex-col gap-6">
      <h2 className="text-lg font-semibold text-foreground">
        {t("admin.feeds")}
      </h2>

      {/* Add Feed (Google News wizard + Custom RSS) */}
      <AddFeedSection feeds={feeds} />

      {/* RSS Feeds */}
      <RssFeedsSection feeds={feeds} isLoading={isLoading} />

      {/* API Sources (only shown if there are any) */}
      <ApiSourcesSection />
    </div>
  );
}

export default function AdminFeedsPage() {
  return (
    <AdminLayout>
      <FeedsContent />
    </AdminLayout>
  );
}
