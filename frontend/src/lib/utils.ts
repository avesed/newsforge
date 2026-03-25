/**
 * Simple className merger. Filters falsy values and joins with space.
 * No external dependencies (clsx/tailwind-merge not installed).
 */
export function cn(...classes: (string | boolean | undefined | null)[]): string {
  return classes.filter(Boolean).join(" ");
}
