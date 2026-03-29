import { useState, useEffect } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Home, BookOpen, Bookmark } from "lucide-react";
import { useAuthStore } from "@/stores/authStore";
import { cn } from "@/lib/utils";

interface NavItem {
  path: string;
  icon: typeof Home;
  labelKey: string;
  requireAuth?: boolean;
}

const NAV_ITEMS: NavItem[] = [
  { path: "/", icon: Home, labelKey: "nav.home" },
  { path: "/stories", icon: BookOpen, labelKey: "nav.stories" },
  { path: "/bookmarks", icon: Bookmark, labelKey: "nav.bookmarks", requireAuth: true },
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

  return (
    <nav
      className={cn(
        "fixed z-50 lg:hidden bottom-nav-float",
        hidden && "bottom-nav-hidden"
      )}
    >
      <div className="flex items-center gap-1 rounded-full bg-white/70 dark:bg-gray-800/60 backdrop-blur-2xl backdrop-saturate-150 shadow-lg shadow-black/5 dark:shadow-black/20 border border-white/20 dark:border-white/10 px-2 py-2">
        {NAV_ITEMS.map((item) => {
          const Icon = item.icon;
          const active = isActive(item.path);
          return (
            <button
              key={item.path}
              onClick={() => handleNavigate(item)}
              aria-label={t(item.labelKey)}
              className={cn(
                "relative flex h-10 w-10 items-center justify-center rounded-full transition-all duration-200",
                active
                  ? "bg-primary/15 text-primary dark:bg-primary/20"
                  : "text-muted-foreground active:scale-95"
              )}
            >
              <Icon
                className={cn(
                  "h-5 w-5 transition-transform duration-200",
                  active && "scale-110"
                )}
              />
            </button>
          );
        })}
      </div>
    </nav>
  );
}
