import { useState, useRef, useEffect, useCallback } from "react";

interface UsePullToRefreshOptions {
  onRefresh: () => Promise<unknown>;
  threshold?: number;
  maxPull?: number;
}

interface UsePullToRefreshReturn {
  containerRef: React.RefObject<HTMLDivElement>;
  pullDistance: number;
  isRefreshing: boolean;
}

export function usePullToRefresh({
  onRefresh,
  threshold = 60,
  maxPull = 100,
}: UsePullToRefreshOptions): UsePullToRefreshReturn {
  const containerRef = useRef<HTMLDivElement>(null);
  const [pullDistance, setPullDistance] = useState(0);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const startYRef = useRef(0);
  const startXRef = useRef(0);
  const pullingRef = useRef(false);
  const pullDistanceRef = useRef(0);
  const refreshingRef = useRef(false);
  const directionLockedRef = useRef(false);

  const handleTouchStart = useCallback((e: TouchEvent) => {
    const touch = e.touches[0];
    if (window.scrollY === 0 && !refreshingRef.current && touch) {
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

    // First significant movement: lock direction
    if (!directionLockedRef.current && (deltaX > 5 || Math.abs(deltaY) > 5)) {
      directionLockedRef.current = true;
      // Horizontal movement dominates — abort pull gesture
      if (deltaX > Math.abs(deltaY)) {
        pullingRef.current = false;
        return;
      }
    }

    if (deltaY > 0 && window.scrollY === 0) {
      e.preventDefault();
      const distance = Math.min(deltaY * 0.4, maxPull);
      pullDistanceRef.current = distance;
      setPullDistance(distance);
    } else {
      pullingRef.current = false;
      pullDistanceRef.current = 0;
      setPullDistance(0);
    }
  }, [maxPull]);

  const handleTouchEnd = useCallback(async () => {
    if (!pullingRef.current || refreshingRef.current) return;
    pullingRef.current = false;

    if (pullDistanceRef.current >= threshold) {
      refreshingRef.current = true;
      setIsRefreshing(true);
      setPullDistance(threshold * 0.6);
      try {
        await onRefresh();
      } finally {
        refreshingRef.current = false;
        setIsRefreshing(false);
        pullDistanceRef.current = 0;
        setPullDistance(0);
      }
    } else {
      pullDistanceRef.current = 0;
      setPullDistance(0);
    }
  }, [threshold, onRefresh]);

  const handleTouchCancel = useCallback(() => {
    pullingRef.current = false;
    pullDistanceRef.current = 0;
    setPullDistance(0);
  }, []);

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

  return { containerRef, pullDistance, isRefreshing };
}
