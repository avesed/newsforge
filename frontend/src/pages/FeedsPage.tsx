import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2, Loader2 } from "lucide-react";
import { getFeeds, createFeed, deleteFeed } from "@/api/feeds";
import { CategoryTag } from "@/components/category/CategoryTag";
import { ALL_CATEGORIES } from "@/types";
import { getErrorMessage } from "@/api/client";

export default function FeedsPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [category, setCategory] = useState("tech");
  const [error, setError] = useState("");

  const { data: feeds, isLoading } = useQuery({
    queryKey: ["feeds"],
    queryFn: getFeeds,
  });

  const createMutation = useMutation({
    mutationFn: createFeed,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["feeds"] });
      setShowForm(false);
      setName("");
      setUrl("");
      setCategory("tech");
      setError("");
    },
    onError: (err) => setError(getErrorMessage(err)),
  });

  const deleteMutation = useMutation({
    mutationFn: deleteFeed,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["feeds"] });
    },
  });

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    createMutation.mutate({ name, url, category });
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-foreground">{t("feeds.title")}</h1>
        <button
          onClick={() => setShowForm(!showForm)}
          className="flex items-center gap-1.5 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground"
        >
          <Plus className="h-4 w-4" />
          {t("feeds.addFeed")}
        </button>
      </div>

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
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={t("feeds.feedName")}
            required
            className="rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground outline-none focus:border-primary"
          />
          <input
            type="url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder={t("feeds.feedUrl")}
            required
            className="rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground outline-none focus:border-primary"
          />
          <select
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            className="rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground outline-none focus:border-primary"
          >
            {ALL_CATEGORIES.map((cat) => (
              <option key={cat.slug} value={cat.slug}>
                {t(`category.${cat.slug}`)}
              </option>
            ))}
          </select>
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
              onClick={() => setShowForm(false)}
              className="rounded-md border border-border px-4 py-2 text-sm text-foreground hover:bg-accent"
            >
              {t("common.cancel")}
            </button>
          </div>
        </form>
      )}

      {isLoading && (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      )}

      {feeds && feeds.length === 0 && (
        <div className="py-12 text-center text-muted-foreground">{t("feeds.noFeeds")}</div>
      )}

      {feeds && feeds.length > 0 && (
        <div className="flex flex-col gap-2">
          {feeds.map((feed) => (
            <div
              key={feed.id}
              className="flex items-center justify-between rounded-lg border border-border bg-card p-4"
            >
              <div className="flex flex-col gap-1">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-foreground">{feed.name}</span>
                  <CategoryTag category={feed.category} />
                </div>
                <span className="text-xs text-muted-foreground">{feed.url}</span>
              </div>
              <button
                onClick={() => deleteMutation.mutate(feed.id)}
                disabled={deleteMutation.isPending}
                className="rounded-md p-2 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
