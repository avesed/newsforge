import { ExternalLink } from "lucide-react";

/** Handles **bold**, *italic*, `code`, ![alt](url) images, and [text](url) links. */
function InlineMarkdown({ text }: { text: string }) {
  const parts: React.ReactNode[] = [];
  // Order matters: images first, then links, then bold, then italic, then inline code
  const regex =
    /(!\[([^\]]*)\]\(([^)]+)\)|\[([^\]]+)\]\((https?:\/\/[^)]+)\)|\*\*(.+?)\*\*|\*(.+?)\*|`([^`]+)`)/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index));
    }
    if (match[3]) {
      // Inline image: ![alt](url) — only allow http/https/data URLs
      const imgSrc = match[3];
      if (/^(https?:|data:image\/)/.test(imgSrc)) {
        parts.push(
          <img
            key={match.index}
            src={imgSrc}
            alt={match[2]}
            className="my-2 inline-block max-w-full rounded-lg"
            loading="lazy"
          />
        );
      }
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
    } else if (match[8]) {
      // Inline code: `code`
      parts.push(
        <code
          key={match.index}
          className="rounded bg-muted px-1.5 py-0.5 text-sm font-mono"
        >
          {match[8]}
        </code>
      );
    }
    lastIndex = match.index + match[0].length;
  }

  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }

  return <>{parts}</>;
}

/**
 * Simple Markdown renderer that handles headers, bold, italic, lists, code blocks,
 * blockquotes, tables, horizontal rules, and paragraphs.
 * No external markdown library needed.
 */
export function MarkdownRenderer({ content }: { content: string }) {
  const rawLines = content.split("\n");
  const elements: React.ReactNode[] = [];
  let listItems: string[] = [];
  let listType: "ul" | "ol" | null = null;
  let keyIndex = 0;

  const nextKey = () => keyIndex++;

  const flushList = () => {
    if (listItems.length > 0 && listType) {
      const Tag = listType;
      elements.push(
        <Tag
          key={`list-${nextKey()}`}
          className={
            listType === "ul"
              ? "list-disc pl-5 my-2"
              : "list-decimal pl-5 my-2"
          }
        >
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

  let i = 0;
  while (i < rawLines.length) {
    const line = rawLines[i] ?? "";

    // --- Code fence blocks ---
    const codeFenceMatch = line.match(/^\s*```(\w*)\s*$/);
    if (codeFenceMatch) {
      flushList();
      const language = codeFenceMatch[1] || "";
      const codeLines: string[] = [];
      i++;
      let foundClosing = false;
      while (i < rawLines.length) {
        if (/^\s*```\s*$/.test(rawLines[i] ?? "")) {
          foundClosing = true;
          i++;
          break;
        }
        codeLines.push(rawLines[i] ?? "");
        i++;
      }
      // If no closing fence found, treat remaining lines as code
      if (!foundClosing) {
        // codeLines already has everything
      }
      elements.push(
        <pre
          key={`code-${nextKey()}`}
          className="my-4 overflow-x-auto rounded-lg bg-muted p-4 text-sm"
        >
          {language && (
            <span className="mb-2 block text-xs font-medium text-muted-foreground">
              {language}
            </span>
          )}
          <code className="font-mono">{codeLines.join("\n")}</code>
        </pre>
      );
      continue;
    }

    // --- Horizontal rules ---
    if (/^(---|\*\*\*|___)$/.test(line.trim())) {
      flushList();
      elements.push(<hr key={`hr-${nextKey()}`} className="my-6 border-border" />);
      i++;
      continue;
    }

    // --- Blockquotes (collect consecutive > lines) ---
    if (line.startsWith("> ") || line === ">") {
      flushList();
      const quoteLines: string[] = [];
      while (
        i < rawLines.length &&
        (rawLines[i]?.startsWith("> ") || rawLines[i] === ">")
      ) {
        const qLine = rawLines[i] ?? "";
        quoteLines.push(qLine.startsWith("> ") ? qLine.slice(2) : "");
        i++;
      }
      elements.push(
        <blockquote
          key={`bq-${nextKey()}`}
          className="my-4 border-l-4 border-primary/30 pl-4 italic text-muted-foreground"
        >
          {quoteLines.map((ql, j) => (
            <p key={j}>
              <InlineMarkdown text={ql} />
            </p>
          ))}
        </blockquote>
      );
      continue;
    }

    // --- Tables (lines containing |) ---
    if (line.includes("|") && line.trim().startsWith("|")) {
      flushList();
      const tableLines: string[] = [];
      while (
        i < rawLines.length &&
        rawLines[i]?.includes("|") &&
        rawLines[i]?.trim().startsWith("|")
      ) {
        tableLines.push(rawLines[i] ?? "");
        i++;
      }
      // Need at least header + separator
      if (tableLines.length >= 2) {
        const parseCells = (row: string) =>
          row
            .split("|")
            .slice(1, -1)
            .map((c) => c.trim());

        const headers = parseCells(tableLines[0]!);
        // tableLines[1] is the separator row (---), skip it
        const isSeparator = (row: string) =>
          parseCells(row).every((c) => /^[-:]+$/.test(c));

        const separatorIndex = isSeparator(tableLines[1]!) ? 1 : -1;
        const dataRows =
          separatorIndex >= 0
            ? tableLines.slice(2).map(parseCells)
            : tableLines.slice(1).map(parseCells);

        elements.push(
          <div key={`table-${nextKey()}`} className="my-4 overflow-x-auto">
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr className="border-b border-border bg-muted/50">
                  {headers.map((h, j) => (
                    <th
                      key={j}
                      className="px-3 py-2 text-left font-medium"
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {dataRows.map((row, j) => (
                  <tr key={j} className="border-b border-border/50">
                    {row.map((cell, k) => (
                      <td key={k} className="px-3 py-2">
                        {cell}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      }
      continue;
    }

    // --- Unordered list ---
    const ulMatch = line.match(/^[-*]\s+(.+)/);
    if (ulMatch?.[1]) {
      if (listType !== "ul") flushList();
      listType = "ul";
      listItems.push(ulMatch[1]);
      i++;
      continue;
    }

    // --- Ordered list ---
    const olMatch = line.match(/^\d+\.\s+(.+)/);
    if (olMatch?.[1]) {
      if (listType !== "ol") flushList();
      listType = "ol";
      listItems.push(olMatch[1]);
      i++;
      continue;
    }

    flushList();

    // --- Block-level image: ![alt](url) — only allow http/https/data URLs ---
    const imgMatch = line.match(/^!\[([^\]]*)\]\(([^)]+)\)$/);
    if (imgMatch && /^(https?:|data:image\/)/.test(imgMatch[2] ?? "")) {
      elements.push(
        <figure key={`img-${nextKey()}`} className="my-4">
          <img
            src={imgMatch[2]}
            alt={imgMatch[1]}
            className="article-img-bleed max-w-full rounded-lg"
            loading="lazy"
          />
          {imgMatch[1] && (
            <figcaption className="text-muted-foreground mt-1 text-center text-xs italic">
              {imgMatch[1]}
            </figcaption>
          )}
        </figure>
      );
      i++;
      continue;
    }

    // --- Block-level link card: [text](url) ---
    const blockLinkMatch = line.match(
      /^\[([^\]]+)\]\((https?:\/\/[^)]+)\)\.?$/
    );
    if (blockLinkMatch) {
      const linkText = blockLinkMatch[1];
      const linkUrl = blockLinkMatch[2];
      let domain = "";
      try {
        domain = new URL(linkUrl!).hostname.replace(/^www\./, "");
      } catch {
        /* */
      }
      elements.push(
        <a
          key={`link-${nextKey()}`}
          href={linkUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="border-border/60 bg-muted/30 hover:bg-muted/60 my-3 flex items-center gap-3 rounded-lg border px-4 py-3 no-underline transition-colors"
        >
          <div className="bg-primary/10 text-primary flex h-9 w-9 shrink-0 items-center justify-center rounded-md">
            <ExternalLink className="h-4 w-4" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="text-foreground truncate text-sm font-medium">
              {linkText}
            </div>
            <div className="text-muted-foreground truncate text-xs">
              {domain}
            </div>
          </div>
        </a>
      );
      i++;
      continue;
    }

    // --- Headers ---
    if (line.startsWith("### ")) {
      elements.push(
        <h3 key={`h3-${nextKey()}`} className="text-base font-bold mt-5 mb-2">
          <InlineMarkdown text={line.slice(4)} />
        </h3>
      );
    } else if (line.startsWith("## ")) {
      elements.push(
        <h2 key={`h2-${nextKey()}`} className="text-lg font-bold mt-6 mb-2">
          <InlineMarkdown text={line.slice(3)} />
        </h2>
      );
    } else if (line.startsWith("# ")) {
      elements.push(
        <h1 key={`h1-${nextKey()}`} className="text-xl font-bold mt-6 mb-3">
          <InlineMarkdown text={line.slice(2)} />
        </h1>
      );
    } else if (line.trim() === "") {
      // skip empty lines
    } else {
      elements.push(
        <p key={`p-${nextKey()}`} className="my-2 leading-relaxed">
          <InlineMarkdown text={line} />
        </p>
      );
    }

    i++;
  }

  flushList();

  return <>{elements}</>;
}
