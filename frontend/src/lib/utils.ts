/**
 * Simple className merger. Filters falsy values and joins with space.
 * No external dependencies (clsx/tailwind-merge not installed).
 */
export function cn(...classes: (string | boolean | undefined | null)[]): string {
  return classes.filter(Boolean).join(" ");
}

/**
 * Extract the real news source from a title that ends with " - Source" or " | Source".
 * Common in aggregator feeds (e.g. Google News: "Headline here - Reuters").
 * Returns { title, source } where source is null if no pattern matched.
 */
export function extractTitleSource(title: string): { title: string; source: string | null } {
  // Match " - Source" or " | Source" at the end, where Source is 2-40 chars (no dash/pipe)
  const match = title.match(/^(.+?)\s+[-|–—]\s+([^-|–—]{2,40})\s*$/);
  if (match && match[1] && match[2]) {
    return { title: match[1].trim(), source: match[2].trim() };
  }
  return { title, source: null };
}
