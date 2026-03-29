import { Outlet, useLocation, useNavigationType } from "react-router-dom";
import { useRef, useEffect } from "react";
import { Header } from "./Header";
import { BottomNav } from "./BottomNav";
import { ScrollToTop } from "@/components/ui/ScrollToTop";
import { ErrorBoundary } from "@/components/ui/ErrorBoundary";

export function Layout() {
  const location = useLocation();
  const navigationType = useNavigationType();
  const prevPathRef = useRef(location.pathname);

  useEffect(() => {
    if (location.pathname !== prevPathRef.current) {
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
        <ErrorBoundary>
          <Outlet />
        </ErrorBoundary>
      </main>
      <BottomNav />
      <ScrollToTop />
    </div>
  );
}
