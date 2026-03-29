import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";

/**
 * iOS-like swipe-from-left-edge to go back.
 * Only active on non-Safari browsers (iOS Safari has native gesture).
 * Only active on detail pages (/article/*, /stories/*).
 */
export function useSwipeBack() {
  const navigate = useNavigate();
  const startXRef = useRef(0);
  const startYRef = useRef(0);
  const swipingRef = useRef(false);

  useEffect(() => {
    // Skip on iOS Safari — it has native back gesture
    const isIOSSafari =
      /iPad|iPhone|iPod/.test(navigator.userAgent) &&
      !navigator.userAgent.includes("CriOS") &&
      !navigator.userAgent.includes("FxiOS") &&
      !(window.navigator as { standalone?: boolean }).standalone;

    if (isIOSSafari) return;

    const handleTouchStart = (e: TouchEvent) => {
      const touch = e.touches[0];
      // Only activate within 20px of left edge
      if (touch && touch.clientX <= 20) {
        // Check if touch target is inside a horizontally scrollable element
        let el = e.target as HTMLElement | null;
        while (el) {
          if (el.scrollWidth > el.clientWidth) {
            const style = window.getComputedStyle(el);
            if (style.overflowX === "auto" || style.overflowX === "scroll") {
              return; // Don't activate swipe-back inside scrollable content
            }
          }
          el = el.parentElement;
        }

        startXRef.current = touch.clientX;
        startYRef.current = touch.clientY;
        swipingRef.current = true;
      }
    };

    const handleTouchMove = (e: TouchEvent) => {
      if (!swipingRef.current) return;
      const touch = e.touches[0];
      if (!touch) return;
      const deltaX = Math.abs(touch.clientX - startXRef.current);
      const deltaY = Math.abs(touch.clientY - startYRef.current);

      // If vertical movement exceeds horizontal, cancel
      if (deltaY > deltaX) {
        swipingRef.current = false;
      }
    };

    const handleTouchEnd = (e: TouchEvent) => {
      if (!swipingRef.current) return;
      swipingRef.current = false;

      const touch = e.changedTouches[0];
      if (!touch) return;
      const deltaX = touch.clientX - startXRef.current;
      const viewportWidth = window.innerWidth;

      if (deltaX > viewportWidth * 0.3) {
        if (window.history.length > 1) {
          navigate(-1);
        } else {
          navigate("/");
        }
      }
    };

    const handleTouchCancel = () => {
      swipingRef.current = false;
    };

    document.addEventListener("touchstart", handleTouchStart, { passive: true });
    document.addEventListener("touchmove", handleTouchMove, { passive: true });
    document.addEventListener("touchend", handleTouchEnd);
    document.addEventListener("touchcancel", handleTouchCancel);

    return () => {
      document.removeEventListener("touchstart", handleTouchStart);
      document.removeEventListener("touchmove", handleTouchMove);
      document.removeEventListener("touchend", handleTouchEnd);
      document.removeEventListener("touchcancel", handleTouchCancel);
    };
  }, [navigate]);
}
