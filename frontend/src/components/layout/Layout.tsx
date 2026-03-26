import { Outlet, useLocation } from "react-router-dom";
import { Header } from "./Header";
import { BottomNav } from "./BottomNav";
import { ScrollToTop } from "@/components/ui/ScrollToTop";

export function Layout() {
  const location = useLocation();

  return (
    <div className="min-h-screen bg-background">
      <Header />
      <main className="mx-auto max-w-6xl px-4 pb-20 pt-4 lg:pb-8">
        <div key={location.pathname} className="animate-page-enter">
          <Outlet />
        </div>
      </main>
      <BottomNav />
      <ScrollToTop />
    </div>
  );
}
