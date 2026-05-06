import { Outlet, useLocation, useNavigationType } from "react-router-dom";
import { useRef, useEffect, useLayoutEffect } from "react";
import { Header } from "./Header";
import { BottomNav } from "./BottomNav";
import { ScrollToTop } from "@/components/ui/ScrollToTop";
import { ErrorBoundary } from "@/components/ui/ErrorBoundary";

const scrollCache = new Map<string, number>();

export function Layout() {
  const location = useLocation();
  const navigationType = useNavigationType();
  const prevPathRef = useRef(location.pathname);

  useEffect(() => {
    if ("scrollRestoration" in window.history) {
      window.history.scrollRestoration = "manual";
    }
  }, []);

  useEffect(() => {
    const key = location.pathname;
    let ticking = false;
    const onScroll = () => {
      if (!ticking) {
        requestAnimationFrame(() => {
          scrollCache.set(key, window.scrollY);
          ticking = false;
        });
        ticking = true;
      }
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [location.pathname]);

  useLayoutEffect(() => {
    if (location.pathname !== prevPathRef.current) {
      if (navigationType === "POP") {
        const saved = scrollCache.get(location.pathname);
        if (saved != null && saved > 0) {
          window.scrollTo(0, saved);
          requestAnimationFrame(() => window.scrollTo(0, saved));
        }
      } else {
        window.scrollTo(0, 0);
      }
      prevPathRef.current = location.pathname;
    }
  }, [location.pathname, navigationType]);

  return (
    <div className="min-h-screen bg-background">
      <Header />
      <main className="mx-auto max-w-6xl px-4 pb-20 pt-4 lg:pb-8">
        <ErrorBoundary>
          <Outlet />
        </ErrorBoundary>
      </main>
      <BottomNav />
      <ScrollToTop />
    </div>
  );
}
