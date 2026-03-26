import { useState, useCallback } from "react";

const STORAGE_KEY = "newsforge_search_history";
const MAX_ITEMS = 10;

function loadHistory(): string[] {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (!stored) return [];
    const parsed: unknown = JSON.parse(stored);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((item): item is string => typeof item === "string");
  } catch {
    return [];
  }
}

function persistHistory(items: string[]): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(items));
  } catch {
    // localStorage full or disabled — silently ignore
  }
}

export function useSearchHistory() {
  const [history, setHistory] = useState<string[]>(loadHistory);

  const addSearch = useCallback((term: string) => {
    const trimmed = term.trim();
    if (!trimmed) return;
    setHistory((prev) => {
      const next = [trimmed, ...prev.filter((h) => h !== trimmed)].slice(0, MAX_ITEMS);
      persistHistory(next);
      return next;
    });
  }, []);

  const removeSearch = useCallback((term: string) => {
    setHistory((prev) => {
      const next = prev.filter((h) => h !== term);
      persistHistory(next);
      return next;
    });
  }, []);

  const clearHistory = useCallback(() => {
    setHistory([]);
    persistHistory([]);
  }, []);

  return { history, addSearch, removeSearch, clearHistory };
}
