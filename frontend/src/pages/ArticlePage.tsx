import { useState, useEffect, useRef, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import {
  ArrowLeft,
  ExternalLink,
  Clock,
  Loader2,
  TrendingUp,
  ChevronDown,
  ChevronUp,
  Bot,
  Sparkles,
} from "lucide-react";
import * as Tabs from "@radix-ui/react-tabs";
import { getArticle, getRelatedArticles } from "@/api/articles";
import { ArticleCard } from "@/components/article/ArticleCard";
import { MarkdownRenderer } from "@/components/article/MarkdownRenderer";
import { useReadHistory } from "@/hooks/useReadHistory";
import { cn } from "@/lib/utils";
import { timeAgo } from "@/lib/timeAgo";
import { CATEGORY_COLORS, type CategorySlug } from "@/types";
import { ArticlePageSkeleton } from "./ArticlePageSkeleton";
import { useReadingStore } from "@/stores/readingStore";

function estimateReadingTime(article: { aiSummary?: string | null; detailedSummary?: string | null; fullText?: string | null; summary?: string | null }): number {
  // Use the longest available content field (not sum of all)
  const candidates = [article.fullText, article.detailedSummary, article.aiSummary, article.summary].filter(Boolean) as string[];
  const text = candidates.reduce((a, b) => (a.length >= b.length ? a : b), "");
  if (!text) return 1;

  const chineseChars = (text.match(/[\u4e00-\u9fff]/g) || []).length;
  const englishWords = text.replace(/[\u4e00-\u9fff]/g, "").split(/\s+/).filter(Boolean).length;

  const minutes = chineseChars / 400 + englishWords / 200;
  return Math.max(1, Math.round(minutes));
}

export default function ArticlePage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { t, i18n } = useTranslation();
  const locale = i18n.language === "zh" ? "zh" : "en";
  const [agentsExpanded, setAgentsExpanded] = useState(false);
  const [activeTab, setActiveTab] = useState("summary");
  const [tabDirection, setTabDirection] = useState<"left" | "right">("right");
  const tabOrder = ["summary", "detailed", "fulltext", "analysis"];
  const [readProgress, setReadProgress] = useState(0);

  // SSE streaming state for analysis tab
  const [analysisContent, setAnalysisContent] = useState("");
  const [analysisLoading, setAnalysisLoading] = useState(false);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const [analysisLoaded, setAnalysisLoaded] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const { fontSize, lineSpacing, contentWidth } = useReadingStore();

  const widthClass = {
    narrow: "max-w-[620px]",
    default: "max-w-[720px]",
    wide: "max-w-[840px]",
  }[contentWidth];

  const proseClass = {
    sm: "prose-sm",
    base: "prose-base",
    lg: "prose-lg",
    xl: "prose-xl",
  }[fontSize];

  const spacingClass = {
    normal: "leading-normal",
    relaxed: "leading-relaxed",
    loose: "leading-loose",
  }[lineSpacing];

  const { isRead, markRead } = useReadHistory();

  const {
    data: article,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ["article", id],
    queryFn: () => getArticle(id!),
    enabled: !!id,
    staleTime: 10 * 60 * 1000,
  });

  const { data: relatedArticles } = useQuery({
    queryKey: ["relatedArticles", article?.id],
    queryFn: () => getRelatedArticles(article!.id),
    enabled: !!article?.id,
    staleTime: 10 * 60 * 1000,
  });

  useEffect(() => {
    if (article?.id) {
      void markRead(article.id);
    }
  }, [article?.id, markRead]);

  // If article already has cached analysis, pre-fill
  useEffect(() => {
    if (article?.aiAnalysis) {
      setAnalysisContent(article.aiAnalysis);
      setAnalysisLoaded(true);
    }
  }, [article?.aiAnalysis]);

  // Stream analysis when the analysis tab is selected
  const streamAnalysis = useCallback(() => {
    if (!article?.id || analysisLoaded || analysisLoading) return;

    setAnalysisLoading(true);
    setAnalysisError(null);
    setAnalysisContent("");

    const controller = new AbortController();
    abortRef.current = controller;

    const token = localStorage.getItem("access_token");
    const headers: Record<string, string> = {
      Accept: "text/event-stream",
    };
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }

    fetch(`/api/v1/articles/${article.id}/stream/analysis`, {
      headers,
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }
        const reader = response.body?.getReader();
        if (!reader) throw new Error("No reader");

        const decoder = new TextDecoder();
        let buffer = "";
        let fullContent = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() ?? "";

          for (const line of lines) {
            if (!line.startsWith("data: ")) continue;
            const jsonStr = line.slice(6).trim();
            if (!jsonStr) continue;

            try {
              const event = JSON.parse(jsonStr) as {
                type: string;
                content?: string;
                message?: string;
                cached?: boolean;
              };

              if (controller.signal.aborted) break;
              if (event.type === "analysis_chunk" && event.content) {
                fullContent += event.content;
                setAnalysisContent(fullContent);
              } else if (event.type === "complete") {
                setAnalysisLoaded(true);
                setAnalysisLoading(false);
              } else if (event.type === "error") {
                setAnalysisError(event.message ?? "Unknown error");
              }
            } catch {
              // skip malformed JSON
            }
          }
        }

        setAnalysisLoading(false);
      })
      .catch((err: unknown) => {
        if (err instanceof DOMException && err.name === "AbortError") return;
        setAnalysisError(
          err instanceof Error ? err.message : "Stream failed"
        );
        setAnalysisLoading(false);
      });
  }, [article?.id, analysisLoaded, analysisLoading]);

  // Trigger streaming when analysis tab is activated
  useEffect(() => {
    if (activeTab === "analysis" && !analysisLoaded && !analysisLoading) {
      streamAnalysis();
    }
  }, [activeTab, analysisLoaded, analysisLoading, streamAnalysis]);

  // Reading progress bar scroll listener
  useEffect(() => {
    let ticking = false;
    const onScroll = () => {
      if (!ticking) {
        requestAnimationFrame(() => {
          const scrollHeight = document.documentElement.scrollHeight - window.innerHeight;
          const progress = scrollHeight > 0 ? Math.min(window.scrollY / scrollHeight, 1) : 0;
          setReadProgress(progress);
          ticking = false;
        });
        ticking = true;
      }
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  // Cleanup abort on unmount
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  if (isLoading) {
    return <ArticlePageSkeleton />;
  }

  if (isError || !article) {
    return (
      <div className="flex flex-col items-center justify-center py-12">
        <p className="text-muted-foreground">{t("common.error")}</p>
        <button
          onClick={() => navigate(-1)}
          className="mt-2 rounded-md bg-primary px-4 py-2 text-sm text-primary-foreground"
        >
          {t("common.back")}
        </button>
      </div>
    );
  }

  const tabTriggerClass =
    "border-b-2 border-transparent px-4 py-2 text-sm font-medium text-muted-foreground transition-colors data-[state=active]:border-primary data-[state=active]:text-primary";

  return (
    <>
    <div
      className="fixed top-0 left-0 z-[60] h-0.5 bg-primary transition-[width] duration-150"
      style={{ width: `${readProgress * 100}%` }}
    />
    <article className={cn("mx-auto", widthClass)}>
      {/* Sticky top bar */}
      <div className="sticky top-0 z-10 -mx-4 mb-6 flex items-center justify-between border-b border-border bg-background/95 px-4 py-3 backdrop-blur supports-[backdrop-filter]:bg-background/80">
        <button
          onClick={() => navigate(-1)}
          className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors"
        >
          <ArrowLeft className="h-4 w-4" />
          {t("common.back")}
        </button>
        {article.sourceUrl && (
          <a
            href={article.sourceUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-sm text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
          >
            <ExternalLink className="h-3.5 w-3.5" />
            {t("article.viewOriginal", "View Original")}
          </a>
        )}
      </div>

      {/* Title */}
      <div className="mb-4">
        <h1 className="text-2xl md:text-3xl font-bold tracking-tight leading-tight text-foreground">
          {locale === "zh" && article.titleZh ? article.titleZh : article.title}
        </h1>
        {locale === "zh" && article.titleZh && (
          <p className="mt-1.5 text-sm text-muted-foreground" lang="en">{article.title}</p>
        )}
      </div>

      {/* Meta row */}
      <div className="flex items-center gap-3 text-sm text-muted-foreground mb-4">
        <span className="font-medium text-foreground/80">
          {article.sourceName}
        </span>
        <span className="flex items-center gap-1">
          <Clock className="h-3.5 w-3.5" />
          {timeAgo(article.publishedAt, locale)}
        </span>
        <span className="text-muted-foreground/60">·</span>
        <span>{t("article.readTime", { min: estimateReadingTime(article) })}</span>
        {article.hasMarketImpact && (
          <span
            className="flex items-center gap-1 text-amber-500 dark:text-amber-400"
            title={article.marketImpactHint ?? undefined}
          >
            <TrendingUp className="h-3.5 w-3.5" />
            {t("article.marketImpact", "Market Impact")}
          </span>
        )}
        {article.sentimentLabel && (
          <span
            className={cn(
              "rounded-full px-2 py-0.5 text-xs font-medium",
              article.sentimentLabel === "positive" &&
                "bg-green-500/10 text-green-500",
              article.sentimentLabel === "negative" &&
                "bg-red-500/10 text-red-500",
              article.sentimentLabel === "neutral" &&
                "bg-blue-500/10 text-blue-400"
            )}
          >
            {t(`sentiment.${article.sentimentLabel}`)}
          </span>
        )}
      </div>

      {/* Category tags */}
      {article.categories && article.categories.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 mb-4">
          {article.categories.map((cat) => {
            const color =
              CATEGORY_COLORS[cat as CategorySlug] ?? CATEGORY_COLORS.other;
            return (
              <span
                key={cat}
                className="rounded-full px-2.5 py-0.5 text-xs font-medium"
                style={{
                  backgroundColor: `${color}20`,
                  color: color,
                }}
              >
                {t(`category.${cat}`, cat)}
              </span>
            );
          })}
          {article.valueScore != null && (
            <span className="inline-flex items-center rounded-full bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">
              {t("article.valueScore", "Value")}: {article.valueScore}
            </span>
          )}
        </div>
      )}

      {/* Separator */}
      <div className="border-b border-border mb-6" />

      {/* Image */}
      {article.imageUrl && (
        <img
          src={article.imageUrl}
          alt=""
          className="mb-6 w-full rounded-lg object-cover"
          style={{ maxHeight: "400px" }}
        />
      )}

      {/* Content tabs */}
      <Tabs.Root
        value={activeTab}
        onValueChange={(val) => {
          const oldIndex = tabOrder.indexOf(activeTab);
          const newIndex = tabOrder.indexOf(val);
          setTabDirection(newIndex > oldIndex ? "right" : "left");
          setActiveTab(val);
        }}
      >
        <Tabs.List className="mb-6 flex gap-1 border-b border-border">
          <Tabs.Trigger value="summary" className={tabTriggerClass}>
            {t("article.summary")}
          </Tabs.Trigger>
          <Tabs.Trigger value="detailed" className={tabTriggerClass}>
            {t("article.detailed")}
          </Tabs.Trigger>
          <Tabs.Trigger value="fulltext" className={tabTriggerClass}>
            {t("article.fullText", "全文")}
          </Tabs.Trigger>
          <Tabs.Trigger value="analysis" className={tabTriggerClass}>
            <span className="flex items-center gap-1.5">
              <Sparkles className="h-3.5 w-3.5" />
              {t("article.analysis")}
            </span>
          </Tabs.Trigger>
        </Tabs.List>

        <Tabs.Content
          value="summary"
          className={cn("prose dark:prose-invert max-w-none", proseClass, spacingClass)}
        >
          <div key={activeTab} className={tabDirection === "right" ? "animate-slide-in-right" : "animate-slide-in-left"}>
            <p className="text-foreground leading-relaxed">{article.aiSummary ?? article.summary}</p>
          </div>
        </Tabs.Content>

        <Tabs.Content
          value="detailed"
          className={cn("prose dark:prose-invert max-w-none", proseClass, spacingClass)}
        >
          <div key={activeTab} className={tabDirection === "right" ? "animate-slide-in-right" : "animate-slide-in-left"}>
            <p className="text-foreground leading-relaxed">
              {article.detailedSummary ?? article.summary}
            </p>
          </div>
        </Tabs.Content>

        <Tabs.Content
          value="fulltext"
          className={cn("prose dark:prose-invert max-w-none", proseClass, spacingClass)}
        >
          <div key={activeTab} className={tabDirection === "right" ? "animate-slide-in-right" : "animate-slide-in-left"}>
            {article.fullText ? (
              <MarkdownRenderer content={locale === "zh" && article.fullTextZh ? article.fullTextZh : article.fullText} />
            ) : (
              <p className="text-muted-foreground py-8 text-center text-sm">
                {t("article.fullTextEmpty", "暂无全文内容")}
              </p>
            )}
          </div>
        </Tabs.Content>

        <Tabs.Content value="analysis" className="min-h-[200px]">
          <div key={activeTab} className={tabDirection === "right" ? "animate-slide-in-right" : "animate-slide-in-left"}>
            {analysisError && (
              <div className="rounded-md border border-red-200 bg-red-50 dark:border-red-900 dark:bg-red-950/50 p-4 mb-4">
                <p className="text-sm text-red-600 dark:text-red-400">
                  {analysisError}
                </p>
                <button
                  onClick={() => {
                    setAnalysisError(null);
                    setAnalysisLoaded(false);
                    streamAnalysis();
                  }}
                  className="mt-2 text-sm text-red-600 dark:text-red-400 underline hover:no-underline"
                >
                  {t("common.retry")}
                </button>
              </div>
            )}
            {analysisContent ? (
              <div className={cn("prose dark:prose-invert max-w-none", proseClass, spacingClass)}>
                <MarkdownRenderer content={analysisContent} />
              </div>
            ) : analysisLoading ? (
              <div className="flex items-center justify-center py-12 gap-2">
                <Loader2 className="h-5 w-5 animate-spin text-primary" />
                <span className="text-sm text-muted-foreground">
                  {t("article.aiAnalyzing", "AI analyzing...")}
                </span>
              </div>
            ) : null}
            {analysisLoading && analysisContent && (
              <div className="mt-2 flex items-center gap-1.5 text-xs text-muted-foreground">
                <Loader2 className="h-3 w-3 animate-spin" />
                {t("article.generating", "Generating...")}
              </div>
            )}
          </div>
        </Tabs.Content>
      </Tabs.Root>

      {/* Agents executed (collapsible) */}
      {article.agentsExecuted && article.agentsExecuted.length > 0 && (
        <div className="mt-6 rounded-lg border border-border bg-muted/30 p-3">
          <button
            onClick={() => setAgentsExpanded((v) => !v)}
            className="flex w-full items-center justify-between text-sm font-medium text-muted-foreground hover:text-foreground"
          >
            <span className="flex items-center gap-1.5">
              <Bot className="h-4 w-4" />
              {t("article.agentsExecuted", "Processing agents")} (
              {article.agentsExecuted.length})
            </span>
            {agentsExpanded ? (
              <ChevronUp className="h-4 w-4" />
            ) : (
              <ChevronDown className="h-4 w-4" />
            )}
          </button>
          {agentsExpanded && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {article.agentsExecuted.map((agent) => (
                <span
                  key={agent}
                  className="inline-flex items-center rounded-md bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground"
                >
                  {agent}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Related Articles */}
      {relatedArticles && relatedArticles.length > 0 && (
        <div className="mt-8 border-t border-border pt-6">
          <h2 className="mb-4 text-lg font-bold text-foreground">
            {t("articles.related")}
          </h2>
          <div className="flex flex-col">
            {relatedArticles.map((related) => (
              <ArticleCard
                key={related.id}
                article={related}
                isRead={isRead(related.id)}
              />
            ))}
          </div>
        </div>
      )}
    </article>
    </>
  );
}
