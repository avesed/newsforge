import { Outlet, useLocation, useNavigationType } from "react-router-dom";
import { useRef, useEffect, useState } from "react";
import { Header } from "./Header";
import { BottomNav } from "./BottomNav";
import { ScrollToTop } from "@/components/ui/ScrollToTop";
import { ErrorBoundary } from "@/components/ui/ErrorBoundary";

const isDetail = (path: string) =>
  path.startsWith("/article/") || /^\/stories\/[^/]+/.test(path);

export function Layout() {
  const location = useLocation();
  const navigationType = useNavigationType();
  const prevPathRef = useRef(location.pathname);
  const [animClass, setAnimClass] = useState("");

  useEffect(() => {
    const prevPath = prevPathRef.current;

    if (location.pathname !== prevPath) {
      // Determine animation direction
      if (isDetail(location.pathname) && !isDetail(prevPath)) {
        setAnimClass("animate-page-slide-in");
      } else if (!isDetail(location.pathname) && isDetail(prevPath)) {
        setAnimClass("animate-page-slide-out");
      } else {
        setAnimClass("animate-page-enter");
      }

      // Only scroll to top on forward navigation, not back/forward (POP)
      if (navigationType !== "POP") {
        window.scrollTo(0, 0);
      }

      prevPathRef.current = location.pathname;
    }
  }, [location.pathname, navigationType]);

  return (
    <div className="min-h-screen bg-background">
      <Header />
      <main className="mx-auto max-w-6xl px-4 pb-20 pt-4 lg:pb-8">
        <div
          className={animClass}
          onAnimationEnd={() => setAnimClass("")}
        >
          <ErrorBoundary>
            <Outlet />
          </ErrorBoundary>
        </div>
      </main>
      <BottomNav />
      <ScrollToTop />
    </div>
  );
}
