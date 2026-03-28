import { create } from "zustand";

type FontSize = "sm" | "base" | "lg" | "xl";
type LineSpacing = "normal" | "relaxed" | "loose";
type ContentWidth = "narrow" | "default" | "wide";

interface ReadingState {
  fontSize: FontSize;
  lineSpacing: LineSpacing;
  contentWidth: ContentWidth;
}

interface ReadingActions {
  setFontSize: (size: FontSize) => void;
  setLineSpacing: (spacing: LineSpacing) => void;
  setContentWidth: (width: ContentWidth) => void;
}

const FONT_SIZES: FontSize[] = ["sm", "base", "lg", "xl"];
const LINE_SPACINGS: LineSpacing[] = ["normal", "relaxed", "loose"];
const CONTENT_WIDTHS: ContentWidth[] = ["narrow", "default", "wide"];

function safeGetItem(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function safeSetItem(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    // Silently fail in restricted environments (e.g., Safari private mode)
  }
}

function getInitialFontSize(): FontSize {
  const stored = safeGetItem("reading-font-size");
  if (stored && FONT_SIZES.includes(stored as FontSize)) {
    return stored as FontSize;
  }
  return "base";
}

function getInitialLineSpacing(): LineSpacing {
  const stored = safeGetItem("reading-line-spacing");
  if (stored && LINE_SPACINGS.includes(stored as LineSpacing)) {
    return stored as LineSpacing;
  }
  return "relaxed";
}

function getInitialContentWidth(): ContentWidth {
  const stored = safeGetItem("reading-content-width");
  if (stored && CONTENT_WIDTHS.includes(stored as ContentWidth)) {
    return stored as ContentWidth;
  }
  return "default";
}

export const useReadingStore = create<ReadingState & ReadingActions>((set) => ({
  fontSize: getInitialFontSize(),
  lineSpacing: getInitialLineSpacing(),
  contentWidth: getInitialContentWidth(),

  setFontSize: (fontSize) => {
    safeSetItem("reading-font-size", fontSize);
    set({ fontSize });
  },

  setLineSpacing: (lineSpacing) => {
    safeSetItem("reading-line-spacing", lineSpacing);
    set({ lineSpacing });
  },

  setContentWidth: (contentWidth) => {
    safeSetItem("reading-content-width", contentWidth);
    set({ contentWidth });
  },
}));
