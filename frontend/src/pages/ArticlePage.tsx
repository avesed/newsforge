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
import { useReadHistory } from "@/hooks/useReadHistory";
import { cn } from "@/lib/utils";
import { timeAgo } from "@/lib/timeAgo";
import { CATEGORY_COLORS, type CategorySlug } from "@/types";
import { ArticlePageSkeleton } from "./ArticlePageSkeleton";

export default function ArticlePage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { t, i18n } = useTranslation();
  const locale = i18n.language === "zh" ? "zh" : "en";
  const [agentsExpanded, setAgentsExpanded] = useState(false);
  const [activeTab, setActiveTab] = useState("summary");

  // SSE streaming state for analysis tab
  const [analysisContent, setAnalysisContent] = useState("");
  const [analysisLoading, setAnalysisLoading] = useState(false);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const [analysisLoaded, setAnalysisLoaded] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

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
    <article className="mx-auto max-w-[720px]">
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
      <h1 className="text-2xl md:text-3xl font-bold tracking-tight leading-tight text-foreground mb-4">
        {article.title}
      </h1>

      {/* Meta row */}
      <div className="flex items-center gap-3 text-sm text-muted-foreground mb-4">
        <span className="font-medium text-foreground/80">
          {article.sourceName}
        </span>
        <span className="flex items-center gap-1">
          <Clock className="h-3.5 w-3.5" />
          {timeAgo(article.publishedAt, locale)}
        </span>
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
      <Tabs.Root value={activeTab} onValueChange={setActiveTab}>
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
          className="prose prose-sm dark:prose-invert max-w-none"
        >
          <p className="text-foreground leading-relaxed">{article.aiSummary ?? article.summary}</p>
        </Tabs.Content>

        <Tabs.Content
          value="detailed"
          className="prose prose-sm dark:prose-invert max-w-none"
        >
          <p className="text-foreground leading-relaxed">
            {article.detailedSummary ?? article.summary}
          </p>
        </Tabs.Content>

        <Tabs.Content
          value="fulltext"
          className="prose prose-sm dark:prose-invert max-w-none"
        >
          {article.fullText ? (
            <MarkdownRenderer content={article.fullText} />
          ) : (
            <p className="text-muted-foreground py-8 text-center text-sm">
              {t("article.fullTextEmpty", "暂无全文内容")}
            </p>
          )}
        </Tabs.Content>

        <Tabs.Content value="analysis" className="min-h-[200px]">
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
            <div className="prose prose-sm dark:prose-invert max-w-none">
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
  );
}

/**
 * Simple Markdown renderer that handles headers, bold, italic, lists, and paragraphs.
 * No external markdown library needed.
 */
function MarkdownRenderer({ content }: { content: string }) {
  const lines = content.split("\n");
  const elements: React.ReactNode[] = [];
  let listItems: string[] = [];
  let listType: "ul" | "ol" | null = null;

  const flushList = () => {
    if (listItems.length > 0 && listType) {
      const Tag = listType;
      elements.push(
        <Tag key={`list-${elements.length}`} className={listType === "ul" ? "list-disc pl-5 my-2" : "list-decimal pl-5 my-2"}>
          {listItems.map((item, i) => (
            <li key={i}>
              <InlineMarkdown text={item} />
            </li>
          ))}
        </Tag>
      );
      listItems = [];
      listType = null;
    }
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i] ?? "";

    // Unordered list
    const ulMatch = line.match(/^[-*]\s+(.+)/);
    if (ulMatch?.[1]) {
      if (listType !== "ul") flushList();
      listType = "ul";
      listItems.push(ulMatch[1]);
      continue;
    }

    // Ordered list
    const olMatch = line.match(/^\d+\.\s+(.+)/);
    if (olMatch?.[1]) {
      if (listType !== "ol") flushList();
      listType = "ol";
      listItems.push(olMatch[1]);
      continue;
    }

    flushList();

    // Block-level image: ![alt](url)
    const imgMatch = line.match(/^!\[([^\]]*)\]\(([^)]+)\)$/);
    if (imgMatch) {
      elements.push(
        <figure key={i} className="my-4">
          <img
            src={imgMatch[2]}
            alt={imgMatch[1]}
            className="max-w-full rounded-lg"
            loading="lazy"
          />
          {imgMatch[1] && (
            <figcaption className="text-muted-foreground mt-1 text-center text-xs italic">
              {imgMatch[1]}
            </figcaption>
          )}
        </figure>
      );
      continue;
    }

    // Block-level link card: [text](url) as the only content on the line
    const blockLinkMatch = line.match(/^\[([^\]]+)\]\((https?:\/\/[^)]+)\)\.?$/);
    if (blockLinkMatch) {
      const linkText = blockLinkMatch[1];
      const linkUrl = blockLinkMatch[2];
      let domain = "";
      try { domain = new URL(linkUrl!).hostname.replace(/^www\./, ""); } catch { /* */ }
      elements.push(
        <a
          key={i}
          href={linkUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="border-border/60 bg-muted/30 hover:bg-muted/60 my-3 flex items-center gap-3 rounded-lg border px-4 py-3 no-underline transition-colors"
        >
          <div className="bg-primary/10 text-primary flex h-9 w-9 shrink-0 items-center justify-center rounded-md">
            <ExternalLink className="h-4 w-4" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="text-foreground truncate text-sm font-medium">{linkText}</div>
            <div className="text-muted-foreground truncate text-xs">{domain}</div>
          </div>
        </a>
      );
      continue;
    }

    // Headers
    if (line.startsWith("### ")) {
      elements.push(
        <h3 key={i} className="text-base font-bold mt-5 mb-2">
          <InlineMarkdown text={line.slice(4)} />
        </h3>
      );
    } else if (line.startsWith("## ")) {
      elements.push(
        <h2 key={i} className="text-lg font-bold mt-6 mb-2">
          <InlineMarkdown text={line.slice(3)} />
        </h2>
      );
    } else if (line.startsWith("# ")) {
      elements.push(
        <h1 key={i} className="text-xl font-bold mt-6 mb-3">
          <InlineMarkdown text={line.slice(2)} />
        </h1>
      );
    } else if (line.trim() === "") {
      // skip empty lines
    } else {
      elements.push(
        <p key={i} className="my-2 leading-relaxed">
          <InlineMarkdown text={line} />
        </p>
      );
    }
  }

  flushList();

  return <>{elements}</>;
}

/** Handles **bold**, *italic*, ![alt](url) images, and [text](url) links. */
function InlineMarkdown({ text }: { text: string }) {
  const parts: React.ReactNode[] = [];
  // Order matters: images first, then links, then bold, then italic
  const regex = /(!\[([^\]]*)\]\(([^)]+)\)|\[([^\]]+)\]\((https?:\/\/[^)]+)\)|\*\*(.+?)\*\*|\*(.+?)\*)/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index));
    }
    if (match[3]) {
      // Inline image: ![alt](url)
      parts.push(
        <img
          key={match.index}
          src={match[3]}
          alt={match[2]}
          className="my-2 inline-block max-w-full rounded-lg"
          loading="lazy"
        />
      );
    } else if (match[5]) {
      // Inline link: [text](url)
      parts.push(
        <a
          key={match.index}
          href={match[5]}
          target="_blank"
          rel="noopener noreferrer"
          className="text-primary hover:text-primary/80 inline-flex items-center gap-0.5 underline underline-offset-2"
        >
          {match[4]}
          <ExternalLink className="inline h-3 w-3 shrink-0" />
        </a>
      );
    } else if (match[6]) {
      parts.push(<strong key={match.index}>{match[6]}</strong>);
    } else if (match[7]) {
      parts.push(<em key={match.index}>{match[7]}</em>);
    }
    lastIndex = match.index + match[0].length;
  }

  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }

  return <>{parts}</>;
}
