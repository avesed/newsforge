/**
 * Returns a human-readable relative time string.
 * Supports both Chinese and English via the optional `locale` parameter.
 */
export function timeAgo(dateStr: string, locale: "zh" | "en" = "zh"): string {
  const now = Date.now();
  const date = new Date(dateStr).getTime();
  const diffMs = now - date;

  if (diffMs < 0) {
    return locale === "zh" ? "刚刚" : "just now";
  }

  const diffSec = Math.floor(diffMs / 1000);
  const diffMin = Math.floor(diffSec / 60);
  const diffHr = Math.floor(diffMin / 60);
  const diffDay = Math.floor(diffHr / 24);
  const diffWeek = Math.floor(diffDay / 7);
  const diffMonth = Math.floor(diffDay / 30);

  if (locale === "zh") {
    if (diffMin < 1) return "刚刚";
    if (diffMin < 60) return `${diffMin}分钟前`;
    if (diffHr < 24) return `${diffHr}小时前`;
    if (diffDay < 7) return `${diffDay}天前`;
    if (diffWeek < 5) return `${diffWeek}周前`;
    if (diffMonth < 12) return `${diffMonth}个月前`;
    return new Date(dateStr).toLocaleDateString("zh-CN");
  }

  // English
  if (diffMin < 1) return "just now";
  if (diffMin < 60) return `${diffMin}m ago`;
  if (diffHr < 24) return `${diffHr}h ago`;
  if (diffDay < 7) return `${diffDay}d ago`;
  if (diffWeek < 5) return `${diffWeek}w ago`;
  if (diffMonth < 12) return `${diffMonth}mo ago`;
  return new Date(dateStr).toLocaleDateString("en-US");
}
