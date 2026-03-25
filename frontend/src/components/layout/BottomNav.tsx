import { useLocation, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Home, Grid3X3, Search, Bookmark, Settings } from "lucide-react";
import { useAuthStore } from "@/stores/authStore";

interface NavItem {
  path: string;
  icon: typeof Home;
  labelKey: string;
  requireAuth?: boolean;
}

const NAV_ITEMS: NavItem[] = [
  { path: "/", icon: Home, labelKey: "nav.home" },
  { path: "/news/tech", icon: Grid3X3, labelKey: "nav.categories" },
  { path: "/search", icon: Search, labelKey: "nav.search" },
  { path: "/bookmarks", icon: Bookmark, labelKey: "nav.bookmarks", requireAuth: true },
  { path: "/settings", icon: Settings, labelKey: "nav.settings", requireAuth: true },
];

export function BottomNav() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const { user } = useAuthStore();

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
    <nav className="fixed bottom-0 left-0 right-0 z-50 border-t border-border bg-background/95 backdrop-blur lg:hidden">
      <div className="flex h-16 items-center justify-around px-2">
        {NAV_ITEMS.map((item) => {
          const Icon = item.icon;
          const active = isActive(item.path);
          return (
            <button
              key={item.path}
              onClick={() => handleNavigate(item)}
              className={`flex flex-1 flex-col items-center gap-1 py-1 ${
                active ? "text-primary" : "text-muted-foreground"
              }`}
            >
              <Icon className="h-5 w-5" />
              <span className="text-[10px] font-medium">{t(item.labelKey)}</span>
            </button>
          );
        })}
      </div>
    </nav>
  );
}
