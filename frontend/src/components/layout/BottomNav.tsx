import { useState, useEffect } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Home, BookOpen, Search, Bookmark, Settings } from "lucide-react";
import { useAuthStore } from "@/stores/authStore";

interface NavItem {
  path: string;
  icon: typeof Home;
  labelKey: string;
  requireAuth?: boolean;
}

const NAV_ITEMS: NavItem[] = [
  { path: "/", icon: Home, labelKey: "nav.home" },
  { path: "/stories", icon: BookOpen, labelKey: "nav.stories" },
  { path: "/search", icon: Search, labelKey: "nav.search" },
  { path: "/bookmarks", icon: Bookmark, labelKey: "nav.bookmarks", requireAuth: true },
  { path: "/settings", icon: Settings, labelKey: "nav.settings", requireAuth: true },
];

export function BottomNav() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const { user } = useAuthStore();
  const isArticlePage = location.pathname.startsWith("/article/");
  const [hidden, setHidden] = useState(isArticlePage);

  useEffect(() => {
    setHidden(location.pathname.startsWith("/article/"));
  }, [location.pathname]);

  useEffect(() => {
    let lastScrollY = window.scrollY;
    let ticking = false;

    const onScroll = () => {
      if (location.pathname.startsWith("/article/")) return;
      if (!ticking) {
        requestAnimationFrame(() => {
          const currentY = window.scrollY;
          if (currentY > lastScrollY && currentY > 100) {
            setHidden(true);
          } else if (currentY < lastScrollY) {
            setHidden(false);
          }
          lastScrollY = currentY;
          ticking = false;
        });
        ticking = true;
      }
    };

    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [location.pathname]);

  const handleNavigate = (item: NavItem) => {
    if (item.requireAuth && !user) {
      navigate("/login");
      return;
    }
    navigate(item.path);
  };

  const isActive = (path: string): boolean => {
    if (path === "/") return location.pathname === "/";
    return location.pathname.startsWith(path);
  };

  const activeIndex = NAV_ITEMS.findIndex((item) => isActive(item.path));

  return (
    <nav className={`fixed bottom-0 left-0 right-0 z-50 border-t border-border bg-background/95 backdrop-blur shadow-[0_-1px_3px_rgba(0,0,0,0.05)] safe-area-bottom lg:hidden transition-transform duration-300 ${hidden ? "translate-y-full" : "translate-y-0"}`}>
      <div className="relative flex h-16 items-center justify-around px-2">
        {NAV_ITEMS.map((item) => {
          const Icon = item.icon;
          const active = isActive(item.path);
          return (
            <button
              key={item.path}
              onClick={() => handleNavigate(item)}
              aria-label={t(item.labelKey)}
              className={`flex flex-1 flex-col items-center gap-1 py-1 ${
                active ? "text-primary" : "text-muted-foreground"
              }`}
            >
              <Icon className="h-5 w-5" />
              <span className="text-[10px] font-medium">{t(item.labelKey)}</span>
            </button>
          );
        })}
        {activeIndex >= 0 && (
          <span
            className="absolute bottom-0 h-1 w-8 rounded-full bg-primary transition-transform duration-200"
            style={{
              left: `${(activeIndex + 0.5) * (100 / NAV_ITEMS.length)}%`,
              transform: "translateX(-50%)",
            }}
          />
        )}
      </div>
    </nav>
  );
}
