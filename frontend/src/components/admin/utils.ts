/** Shared input class for admin forms. */
export const INPUT_CLASS =
  "rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground outline-none focus:border-primary";

/** Relative time helper (e.g. "5m", "2h", "3d"). */
export function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const seconds = Math.floor(diff / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h`;
  const days = Math.floor(hours / 24);
  return `${days}d`;
}
