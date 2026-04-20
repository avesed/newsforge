import { useState, useRef, useEffect, useCallback } from "react";

interface UsePullToRefreshOptions {
  onRefresh: () => Promise<unknown>;
  threshold?: number;
  maxPull?: number;
}

interface UsePullToRefreshReturn {
  containerRef: React.RefObject<HTMLDivElement>;
  indicatorRef: React.RefObject<HTMLDivElement>;
  isRefreshing: boolean;
}

export function usePullToRefresh({
  onRefresh,
  threshold = 60,
  maxPull = 100,
}: UsePullToRefreshOptions): UsePullToRefreshReturn {
  const containerRef = useRef<HTMLDivElement>(null);
  const indicatorRef = useRef<HTMLDivElement>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);

  const startYRef = useRef(0);
  const startXRef = useRef(0);
  const pullingRef = useRef(false);
  const pullDistanceRef = useRef(0);
  const refreshingRef = useRef(false);
  const directionLockedRef = useRef(false);

  // Direct DOM update — no React re-render per frame
  const updateIndicator = useCallback((distance: number, animate = false) => {
    const el = indicatorRef.current;
    if (!el) return;
    // Disable transition during active pulling; enable for snap/collapse
    el.style.transition = animate
      ? "height 250ms ease-out, opacity 200ms ease-out"
      : "none";
    el.style.height = `${distance}px`;
    el.style.opacity = distance > 0 ? "1" : "0";
    // Rotate the spinner icon inside
    const icon = el.querySelector("[data-pull-icon]") as HTMLElement | null;
    if (icon) {
      icon.style.transform = `rotate(${distance * 3}deg)`;
      icon.style.opacity = `${Math.min(distance / threshold, 1)}`;
    }
  }, [threshold]);

  // Clear inline styles on icon so CSS animate-spin can take over
  const releaseIconStyle = useCallback(() => {
    const el = indicatorRef.current;
    if (!el) return;
    const icon = el.querySelector("[data-pull-icon]") as HTMLElement | null;
    if (icon) {
      icon.style.transform = "";
      icon.style.opacity = "";
    }
  }, []);

  const handleTouchStart = useCallback((e: TouchEvent) => {
    const touch = e.touches[0];
    if (window.scrollY <= 1 && !refreshingRef.current && touch) {
      startYRef.current = touch.clientY;
      startXRef.current = touch.clientX;
      pullingRef.current = true;
      directionLockedRef.current = false;
    }
  }, []);

  const handleTouchMove = useCallback((e: TouchEvent) => {
    if (!pullingRef.current || refreshingRef.current) return;
    const touch = e.touches[0];
    if (!touch) return;

    const deltaY = touch.clientY - startYRef.current;
    const deltaX = Math.abs(touch.clientX - startXRef.current);

    // Lock direction on first significant movement
    if (!directionLockedRef.current && (deltaX > 5 || Math.abs(deltaY) > 5)) {
      directionLockedRef.current = true;
      if (deltaX > Math.abs(deltaY)) {
        pullingRef.current = false;
        return;
      }
    }

    if (deltaY > 0 && window.scrollY <= 1) {
      e.preventDefault();
      const distance = Math.min(deltaY * 0.4, maxPull);
      pullDistanceRef.current = distance;
      updateIndicator(distance);
    } else {
      pullingRef.current = false;
      pullDistanceRef.current = 0;
      updateIndicator(0);
    }
  }, [maxPull, updateIndicator]);

  const handleTouchEnd = useCallback(async () => {
    if (!pullingRef.current || refreshingRef.current) return;
    pullingRef.current = false;

    if (pullDistanceRef.current >= threshold) {
      refreshingRef.current = true;
      setIsRefreshing(true);
      // Snap indicator to loading position (animated)
      const snapHeight = threshold * 0.6;
      updateIndicator(snapHeight, true);
      releaseIconStyle();
      try {
        const minDisplay = new Promise((r) => setTimeout(r, 1000));
        await Promise.all([onRefresh(), minDisplay]);
      } finally {
        refreshingRef.current = false;
        setIsRefreshing(false);
        pullDistanceRef.current = 0;
        updateIndicator(0, true);
      }
    } else {
      pullDistanceRef.current = 0;
      updateIndicator(0, true);
    }
  }, [threshold, onRefresh, updateIndicator, releaseIconStyle]);

  const handleTouchCancel = useCallback(() => {
    pullingRef.current = false;
    pullDistanceRef.current = 0;
    updateIndicator(0);
  }, [updateIndicator]);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    el.addEventListener("touchstart", handleTouchStart, { passive: true });
    el.addEventListener("touchmove", handleTouchMove, { passive: false });
    el.addEventListener("touchend", handleTouchEnd);
    el.addEventListener("touchcancel", handleTouchCancel);

    return () => {
      el.removeEventListener("touchstart", handleTouchStart);
      el.removeEventListener("touchmove", handleTouchMove);
      el.removeEventListener("touchend", handleTouchEnd);
      el.removeEventListener("touchcancel", handleTouchCancel);
    };
  }, [handleTouchStart, handleTouchMove, handleTouchEnd, handleTouchCancel]);

  return { containerRef, indicatorRef, isRefreshing };
}
