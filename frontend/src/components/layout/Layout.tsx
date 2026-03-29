import { Outlet, useLocation } from "react-router-dom";
import { useRef, useEffect } from "react";
import { Header } from "./Header";
import { BottomNav } from "./BottomNav";
import { ScrollToTop } from "@/components/ui/ScrollToTop";
import { ErrorBoundary } from "@/components/ui/ErrorBoundary";

export function Layout() {
  const location = useLocation();
  const prevPathRef = useRef(location.pathname);

  // Determine animation direction
  const isDetail = (path: string) => path.startsWith("/article/") || /^\/stories\/[^/]+/.test(path);
  const prevPath = prevPathRef.current;

  let animationClass = "animate-page-enter"; // default fade
  if (isDetail(location.pathname) && !isDetail(prevPath)) {
    animationClass = "animate-page-slide-in";
  } else if (!isDetail(location.pathname) && isDetail(prevPath)) {
    animationClass = "animate-page-slide-out";
  }

  // Scroll to top and update ref on route change
  useEffect(() => {
    window.scrollTo(0, 0);
    prevPathRef.current = location.pathname;
  }, [location.pathname]);

  return (
    <div className="min-h-screen bg-background">
      <Header />
      <main className="mx-auto max-w-6xl px-4 pb-20 pt-4 lg:pb-8">
        <div key={location.pathname} className={animationClass}>
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
