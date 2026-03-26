import {
  useState,
  useEffect,
  useRef,
  useCallback,
  type FormEvent,
} from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  Search,
  SearchX,
  Loader2,
  SlidersHorizontal,
  ChevronDown,
  ChevronUp,
  ExternalLink,
  Download,
  Check,
  Clock,
  X,
} from "lucide-react";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import {
  searchArticles,
  searchSuggest,
  searchExternal,
  importExternalArticles,
  type SearchParams,
} from "@/api/search";
import { getErrorMessage } from "@/api/client";
import { EmptyState } from "@/components/EmptyState";
import { ArticleCard } from "@/components/article/ArticleCard";
import { toast } from "@/stores/toastStore";
import { useReadHistory } from "@/hooks/useReadHistory";
import { ALL_CATEGORIES, CATEGORY_COLORS } from "@/types";
import type { ExternalSearchResult, CategorySlug } from "@/types";
import { cn } from "@/lib/utils";
import { useSearchHistory } from "@/hooks/useSearchHistory";

type SortOption = "relevance" | "date" | "value_score";

function formatRelativeTime(dateStr: string): string {
  const now = Date.now();
  const date = new Date(dateStr).getTime();
  const diffMs = now - date;
  const diffMin = Math.floor(diffMs / 60000);
  if (diffMin < 1) return "just now";
  if (diffMin < 60) return `${diffMin}m`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h`;
  const diffDay = Math.floor(diffHr / 24);
  if (diffDay < 30) return `${diffDay}d`;
  return new Date(dateStr).toLocaleDateString();
}

// --- Autocomplete Suggestion Dropdown ---

function SuggestionDropdown({
  suggestions,
  visible,
  onSelect,
  activeIndex,
}: {
  suggestions: Array<{ title: string; articleId: string }>;
  visible: boolean;
  onSelect: (articleId: string) => void;
  activeIndex: number;
}) {
  if (!visible || suggestions.length === 0) return null;
  return (
    <ul className="absolute left-0 right-0 top-full z-50 mt-1 max-h-64 overflow-y-auto rounded-md border border-border bg-card shadow-lg">
      {suggestions.map((s, idx) => (
        <li key={s.articleId}>
          <button
            type="button"
            onMouseDown={(e) => {
              e.preventDefault();
              onSelect(s.articleId);
            }}
            className={`w-full px-4 py-2.5 text-left text-sm text-foreground hover:bg-accent ${
              idx === activeIndex ? "bg-accent" : ""
            }`}
          >
            {s.title}
          </button>
        </li>
      ))}
    </ul>
  );
}

// --- External Result Card ---

function ExternalResultCard({
  result,
  onImport,
  importingUrls,
  importedUrls,
}: {
  result: ExternalSearchResult;
  onImport: (url: string) => void;
  importingUrls: Set<string>;
  importedUrls: Set<string>;
}) {
  const { t } = useTranslation();
  const isImporting = importingUrls.has(result.url);
  const isImported = importedUrls.has(result.url);

  return (
    <div className="rounded-lg border border-border bg-card p-4 transition-all hover:shadow-md">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <a
            href={result.url}
            target="_blank"
            rel="noopener noreferrer"
            className="line-clamp-2 text-base font-semibold leading-tight text-foreground hover:text-primary"
          >
            {result.title}
            <ExternalLink className="ml-1 inline-block h-3.5 w-3.5" />
          </a>
          {result.summary && (
            <p className="mt-1.5 line-clamp-2 text-sm text-muted-foreground">
              {result.summary}
            </p>
          )}
          <div className="mt-2 flex items-center gap-3 text-xs text-muted-foreground">
            <span>{result.sourceName}</span>
            {result.publishedAt && (
              <span className="flex items-center gap-1">
                <Clock className="h-3 w-3" />
                {formatRelativeTime(result.publishedAt)}
              </span>
            )}
            <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium">
              {result.provider}
            </span>
          </div>
        </div>
        <button
          type="button"
          onClick={() => onImport(result.url)}
          disabled={isImporting || isImported}
          className={`flex-shrink-0 rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
            isImported
              ? "bg-green-500/15 text-green-600 dark:text-green-400"
              : isImporting
                ? "bg-muted text-muted-foreground"
                : "bg-primary text-primary-foreground hover:bg-primary/90"
          }`}
        >
          {isImported ? (
            <span className="flex items-center gap-1">
              <Check className="h-3 w-3" />
              {t("search.imported")}
            </span>
          ) : isImporting ? (
            <span className="flex items-center gap-1">
              <Loader2 className="h-3 w-3 animate-spin" />
              {t("search.importing")}
            </span>
          ) : (
            <span className="flex items-center gap-1">
              <Download className="h-3 w-3" />
              {t("search.import")}
            </span>
          )}
        </button>
      </div>
    </div>
  );
}

// --- Main SearchPage ---

export default function SearchPage() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();

  // Read initial values from URL
  const initialQ = searchParams.get("q") ?? "";
  const initialCategory = searchParams.get("category") ?? "";
  const initialLanguage = searchParams.get("language") ?? "";
  const initialDateFrom = searchParams.get("date_from") ?? "";
  const initialDateTo = searchParams.get("date_to") ?? "";
  const initialMarketImpact = searchParams.get("has_market_impact");
  const initialSort = (searchParams.get("sort") as SortOption | null) ?? "relevance";

  const [query, setQuery] = useState(initialQ);
  const [searchTerm, setSearchTerm] = useState(initialQ);
  const [category, setCategory] = useState(initialCategory);
  const [language, setLanguage] = useState(initialLanguage);
  const [dateFrom, setDateFrom] = useState(initialDateFrom);
  const [dateTo, setDateTo] = useState(initialDateTo);
  const [hasMarketImpact, setHasMarketImpact] = useState(
    initialMarketImpact === "true"
  );
  const [sort, setSort] = useState<SortOption>(initialSort);
  const [filtersOpen, setFiltersOpen] = useState(false);

  // Autocomplete state
  const [suggestionsOpen, setSuggestionsOpen] = useState(false);
  const [activeSuggestionIndex, setActiveSuggestionIndex] = useState(-1);
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  // Import state
  const [importingUrls, setImportingUrls] = useState<Set<string>>(new Set());
  const [importedUrls, setImportedUrls] = useState<Set<string>>(new Set());
  const { isRead } = useReadHistory();
  const { history, addSearch, removeSearch, clearHistory } = useSearchHistory();
  const [historyOpen, setHistoryOpen] = useState(false);

  // Debounce for autocomplete
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedQuery(query.trim());
    }, 300);
    return () => clearTimeout(timer);
  }, [query]);

  // Suggestions query
  const { data: suggestData } = useQuery({
    queryKey: ["searchSuggest", debouncedQuery],
    queryFn: () => searchSuggest(debouncedQuery, 8),
    enabled: debouncedQuery.length >= 2 && suggestionsOpen,
    staleTime: 30 * 1000,
  });

  const suggestions = suggestData?.suggestions ?? [];

  // Build search params for the API
  const buildSearchParams = useCallback(
    (page: number): SearchParams => {
      const params: SearchParams = { q: searchTerm, page, pageSize: 20 };
      if (category) params.category = category;
      if (language) params.language = language;
      if (dateFrom) params.dateFrom = dateFrom;
      if (dateTo) params.dateTo = dateTo;
      if (hasMarketImpact) params.hasMarketImpact = true;
      if (sort !== "relevance") params.sort = sort;
      return params;
    },
    [searchTerm, category, language, dateFrom, dateTo, hasMarketImpact, sort]
  );

  // Internal search (infinite query)
  const {
    data: searchData,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
    isLoading: isSearching,
    isError: isSearchError,
  } = useInfiniteQuery({
    queryKey: [
      "search",
      searchTerm,
      category,
      language,
      dateFrom,
      dateTo,
      hasMarketImpact,
      sort,
    ],
    queryFn: ({ pageParam }) => searchArticles(buildSearchParams(pageParam)),
    initialPageParam: 1,
    getNextPageParam: (lastPage) =>
      lastPage.hasMore ? lastPage.page + 1 : undefined,
    enabled: searchTerm.length > 0,
    staleTime: 5 * 60 * 1000,
  });

  // External search query
  const {
    data: externalData,
    isLoading: isExternalLoading,
  } = useQuery({
    queryKey: ["searchExternal", searchTerm, dateFrom, dateTo],
    queryFn: () =>
      searchExternal(
        searchTerm,
        i18n.language === "zh" ? "zh-CN" : "en",
        20,
        dateFrom || undefined,
        dateTo || undefined,
      ),
    enabled: searchTerm.length > 0,
    staleTime: 5 * 60 * 1000,
  });

  // Sync search to URL params
  const syncUrlParams = useCallback(
    (term: string) => {
      const params = new URLSearchParams();
      if (term) params.set("q", term);
      if (category) params.set("category", category);
      if (language) params.set("language", language);
      if (dateFrom) params.set("date_from", dateFrom);
      if (dateTo) params.set("date_to", dateTo);
      if (hasMarketImpact) params.set("has_market_impact", "true");
      if (sort !== "relevance") params.set("sort", sort);
      setSearchParams(params, { replace: true });
    },
    [category, language, dateFrom, dateTo, hasMarketImpact, sort, setSearchParams]
  );

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    const trimmed = query.trim();
    if (trimmed.length > 0) {
      setSearchTerm(trimmed);
      addSearch(trimmed);
      setSuggestionsOpen(false);
      setHistoryOpen(false);
      syncUrlParams(trimmed);
    }
  };

  // Re-run search when filters change (only if already searching)
  useEffect(() => {
    if (searchTerm) {
      syncUrlParams(searchTerm);
    }
  }, [category, language, dateFrom, dateTo, hasMarketImpact, sort, searchTerm, syncUrlParams]);

  const handleSuggestionSelect = (articleId: string) => {
    setSuggestionsOpen(false);
    navigate(`/article/${articleId}`);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (!suggestionsOpen || suggestions.length === 0) return;

    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveSuggestionIndex((prev) =>
        prev < suggestions.length - 1 ? prev + 1 : 0
      );
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveSuggestionIndex((prev) =>
        prev > 0 ? prev - 1 : suggestions.length - 1
      );
    } else if (e.key === "Enter" && activeSuggestionIndex >= 0) {
      e.preventDefault();
      const selected = suggestions[activeSuggestionIndex];
      if (selected) {
        handleSuggestionSelect(selected.articleId);
      }
    } else if (e.key === "Escape") {
      setSuggestionsOpen(false);
    }
  };

  const handleImport = async (url: string) => {
    setImportingUrls((prev) => new Set(prev).add(url));
    try {
      await importExternalArticles([url]);
      setImportedUrls((prev) => new Set(prev).add(url));
      toast({ variant: "success", title: t("search.imported") });
    } catch (err) {
      const message = getErrorMessage(err);
      toast({ variant: "error", title: t("search.importFailed"), description: message });
    } finally {
      setImportingUrls((prev) => {
        const next = new Set(prev);
        next.delete(url);
        return next;
      });
    }
  };

  const articles = searchData?.pages.flatMap((page) => page.articles) ?? [];
  const firstPage = searchData?.pages[0];
  const totalResults = firstPage?.total ?? 0;
  const searchMode = firstPage?.searchMode ?? "";
  const queryTimeMs = firstPage?.queryTimeMs ?? 0;

  const hasSearched = searchTerm.length > 0;

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-2xl font-bold text-foreground">{t("search.title")}</h1>

      {/* Search Input */}
      <form onSubmit={handleSubmit} className="flex gap-2">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => {
              const val = e.target.value;
              setQuery(val);
              if (val.trim().length >= 2) {
                setSuggestionsOpen(true);
                setHistoryOpen(false);
              } else {
                setSuggestionsOpen(false);
                setHistoryOpen(val.trim().length === 0 && history.length > 0);
              }
              setActiveSuggestionIndex(-1);
            }}
            onFocus={() => {
              if (query.trim().length >= 2) {
                setSuggestionsOpen(true);
              } else if (query.trim().length === 0 && history.length > 0) {
                setHistoryOpen(true);
              }
            }}
            onBlur={() => {
              // Delay to allow click on suggestion / history item
              setTimeout(() => {
                setSuggestionsOpen(false);
                setHistoryOpen(false);
              }, 200);
            }}
            onKeyDown={handleKeyDown}
            placeholder={t("search.placeholder")}
            className="w-full rounded-md border border-border bg-background py-2.5 pl-10 pr-4 text-sm text-foreground outline-none focus:border-primary focus:ring-1 focus:ring-primary"
            autoFocus
            autoComplete="off"
          />
          <SuggestionDropdown
            suggestions={suggestions}
            visible={suggestionsOpen && suggestions.length > 0}
            onSelect={handleSuggestionSelect}
            activeIndex={activeSuggestionIndex}
          />
          {historyOpen && !suggestionsOpen && query.trim().length === 0 && history.length > 0 && (
            <div className="absolute left-0 right-0 top-full z-50 mt-1 max-h-64 overflow-y-auto rounded-md border border-border bg-card shadow-lg">
              <div className="flex items-center justify-between px-4 py-2 text-xs font-medium text-muted-foreground">
                <span>{t("search.recentSearches")}</span>
                <button
                  type="button"
                  onMouseDown={(e) => {
                    e.preventDefault();
                    clearHistory();
                    setHistoryOpen(false);
                  }}
                  className="text-xs text-muted-foreground hover:text-foreground"
                >
                  {t("search.clearHistory")}
                </button>
              </div>
              {history.map((term) => (
                <div
                  key={term}
                  className="flex items-center justify-between px-4 py-2.5 hover:bg-accent"
                >
                  <button
                    type="button"
                    onMouseDown={(e) => {
                      e.preventDefault();
                      setQuery(term);
                      setSearchTerm(term);
                      addSearch(term);
                      setHistoryOpen(false);
                      syncUrlParams(term);
                    }}
                    className="flex min-w-0 flex-1 items-center gap-2 text-left text-sm text-foreground"
                  >
                    <Clock className="h-3.5 w-3.5 flex-shrink-0 text-muted-foreground" />
                    <span className="truncate">{term}</span>
                  </button>
                  <button
                    type="button"
                    onMouseDown={(e) => {
                      e.preventDefault();
                      removeSearch(term);
                    }}
                    className="ml-2 flex-shrink-0 text-muted-foreground hover:text-foreground"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
        <button
          type="submit"
          className="rounded-md bg-primary px-4 py-2.5 text-sm font-medium text-primary-foreground hover:bg-primary/90"
        >
          {t("search.title")}
        </button>
        <button
          type="button"
          onClick={() => setFiltersOpen((v) => !v)}
          className={`rounded-md border px-3 py-2.5 text-sm transition-colors ${
            filtersOpen
              ? "border-primary bg-primary/10 text-primary"
              : "border-border text-muted-foreground hover:bg-accent hover:text-foreground"
          }`}
          aria-label={t("search.filters")}
        >
          <SlidersHorizontal className="h-4 w-4" />
        </button>
      </form>

      {/* Filters Panel */}
      <div className="collapsible-panel" data-open={filtersOpen}>
        <div>
        <div className="rounded-lg border border-border bg-card p-4">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-foreground">
              {t("search.filters")}
            </h3>
            <button
              type="button"
              onClick={() => setFiltersOpen(false)}
              className="text-muted-foreground hover:text-foreground"
            >
              {filtersOpen ? (
                <ChevronUp className="h-4 w-4" />
              ) : (
                <ChevronDown className="h-4 w-4" />
              )}
            </button>
          </div>
          <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {/* Category */}
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">
                {t("search.category")}
              </label>
              <div className="scrollbar-hide flex gap-1.5 overflow-x-auto pb-1">
                <button
                  type="button"
                  onClick={() => setCategory("")}
                  className={cn(
                    "whitespace-nowrap rounded-full px-3 py-1.5 text-xs font-medium transition-colors",
                    !category ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground hover:bg-accent"
                  )}
                >
                  {t("search.allCategories")}
                </button>
                {ALL_CATEGORIES.map((cat) => {
                  const isActive = category === cat.slug;
                  const color = CATEGORY_COLORS[cat.slug as CategorySlug];
                  return (
                    <button
                      key={cat.slug}
                      type="button"
                      onClick={() => setCategory(isActive ? "" : cat.slug)}
                      className="whitespace-nowrap rounded-full px-3 py-1.5 text-xs font-medium transition-colors"
                      style={isActive
                        ? { backgroundColor: color, color: "#fff" }
                        : { backgroundColor: `${color}15`, color }
                      }
                    >
                      {i18n.language === "zh" ? cat.nameZh : cat.name}
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Language */}
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">
                {t("search.language")}
              </label>
              <select
                value={language}
                onChange={(e) => setLanguage(e.target.value)}
                className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground outline-none focus:border-primary"
              >
                <option value="">{t("search.allLanguages")}</option>
                <option value="en">English</option>
                <option value="zh">中文</option>
              </select>
            </div>

            {/* Date From */}
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">
                {t("search.dateFrom")}
              </label>
              <div className="relative">
                <input
                  type="date"
                  value={dateFrom}
                  onChange={(e) => setDateFrom(e.target.value)}
                  className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground outline-none focus:border-primary"
                />
                {dateFrom && (
                  <button
                    type="button"
                    onClick={() => setDateFrom("")}
                    className="absolute right-8 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                )}
              </div>
            </div>

            {/* Date To */}
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">
                {t("search.dateTo")}
              </label>
              <div className="relative">
                <input
                  type="date"
                  value={dateTo}
                  onChange={(e) => setDateTo(e.target.value)}
                  className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground outline-none focus:border-primary"
                />
                {dateTo && (
                  <button
                    type="button"
                    onClick={() => setDateTo("")}
                    className="absolute right-8 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                )}
              </div>
            </div>
          </div>

          {/* Second row: market impact + sort */}
          <div className="mt-3 flex flex-wrap items-center gap-4">
            <label className="flex cursor-pointer items-center gap-2 text-sm text-foreground">
              <input
                type="checkbox"
                checked={hasMarketImpact}
                onChange={(e) => setHasMarketImpact(e.target.checked)}
                className="h-4 w-4 rounded border-border text-primary accent-primary"
              />
              {t("search.marketImpact")}
            </label>

            <div className="flex items-center gap-2">
              <label className="text-xs font-medium text-muted-foreground">
                {t("search.sortBy")}
              </label>
              <select
                value={sort}
                onChange={(e) => setSort(e.target.value as SortOption)}
                className="rounded-md border border-border bg-background px-3 py-1.5 text-sm text-foreground outline-none focus:border-primary"
              >
                <option value="relevance">{t("search.sortRelevance")}</option>
                <option value="date">{t("search.sortDate")}</option>
                <option value="value_score">{t("search.sortValue")}</option>
              </select>
            </div>
          </div>
        </div>
        </div>
      </div>

      {/* Loading state */}
      {isSearching && (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          <span className="ml-2 text-muted-foreground">{t("common.loading")}</span>
        </div>
      )}

      {/* Error state */}
      {isSearchError && (
        <div className="py-12 text-center text-muted-foreground">
          {t("common.error")}
        </div>
      )}

      {/* Results metadata */}
      {hasSearched && !isSearching && firstPage && (
        <div className="text-sm text-muted-foreground">
          {t("search.resultCount", { count: totalResults })}{" "}
          {t("search.resultMeta", { mode: searchMode, time: queryTimeMs })}
        </div>
      )}

      {/* No results */}
      {hasSearched && !isSearching && !isSearchError && articles.length === 0 && (
        <EmptyState
          icon={SearchX}
          title={t("search.noResults")}
          description={t("search.noResultsHint")}
        />
      )}

      {/* Internal results */}
      {articles.length > 0 && (
        <div className="flex flex-col gap-3">
          {articles.map((article) => (
            <ArticleCard key={article.id} article={article} isRead={isRead(article.id)} />
          ))}

          {/* Load more */}
          {hasNextPage && (
            <div className="flex justify-center py-2">
              <button
                type="button"
                onClick={() => void fetchNextPage()}
                disabled={isFetchingNextPage}
                className="rounded-md border border-border px-6 py-2 text-sm font-medium text-foreground hover:bg-accent disabled:opacity-50"
              >
                {isFetchingNextPage ? (
                  <span className="flex items-center gap-2">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    {t("common.loading")}
                  </span>
                ) : (
                  t("search.loadMore")
                )}
              </button>
            </div>
          )}
        </div>
      )}

      {/* External results */}
      {hasSearched &&
        !isSearching &&
        externalData &&
        externalData.results.length > 0 && (
          <div className="mt-4 flex flex-col gap-3">
            <div className="flex items-center gap-2">
              <h2 className="text-lg font-semibold text-foreground">
                {t("search.externalResults")}
              </h2>
              {isExternalLoading && (
                <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
              )}
            </div>
            {externalData.results.map((result) => (
              <ExternalResultCard
                key={result.url}
                result={result}
                onImport={(url) => void handleImport(url)}
                importingUrls={importingUrls}
                importedUrls={importedUrls}
              />
            ))}
          </div>
        )}

      {/* No external results notice */}
      {hasSearched &&
        !isSearching &&
        externalData &&
        externalData.results.length === 0 &&
        articles.length === 0 && (
          <p className="text-center text-sm text-muted-foreground">
            {t("search.noExternalResults")}
          </p>
        )}
    </div>
  );
}
