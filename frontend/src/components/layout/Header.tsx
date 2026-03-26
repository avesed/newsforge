import { useState, useEffect } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Search, Sun, Moon, LogIn, LogOut, Settings, Shield, History } from "lucide-react";
import { useThemeStore } from "@/stores/themeStore";
import { useAuthStore } from "@/stores/authStore";
import { cn } from "@/lib/utils";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";

const AVATAR_COLORS = [
  "#10b981", "#3b82f6", "#ef4444", "#f59e0b", "#8b5cf6",
  "#06b6d4", "#6366f1", "#14b8a6", "#ec4899", "#f97316",
];

function getUserColor(name: string): string {
  let hash = 0;
  for (let i = 0; i < name.length; i++) {
    hash = name.charCodeAt(i) + ((hash << 5) - hash);
  }
  return AVATAR_COLORS[Math.abs(hash) % AVATAR_COLORS.length] ?? "#6b7280";
}

export function Header() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const { theme, toggle: toggleTheme } = useThemeStore();
  const { user, logout } = useAuthStore();
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const handleScroll = () => {
      setScrolled(window.scrollY > 0);
    };
    window.addEventListener("scroll", handleScroll, { passive: true });
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  const handleLogout = async () => {
    await logout();
    navigate("/");
  };

  const toggleLang = () => {
    const next = i18n.language === "zh" ? "en" : "zh";
    void i18n.changeLanguage(next);
    localStorage.setItem("language", next);
  };

  return (
    <header className={cn("sticky top-0 z-50 border-b border-border bg-background/95 backdrop-blur transition-shadow", scrolled && "shadow-sm")}>
      <div className="mx-auto max-w-6xl px-4">
        {/* Top bar */}
        <div className="flex h-14 items-center justify-between">
          <Link to="/" className="flex items-center gap-2">
            <span className="text-xl font-bold text-primary">NewsForge</span>
          </Link>

          <div className="flex items-center gap-2">
            <button
              onClick={() => navigate("/search")}
              className="rounded-full p-2 text-muted-foreground hover:bg-accent hover:text-foreground"
              aria-label={t("nav.search")}
            >
              <Search className="h-5 w-5" />
            </button>

            <button
              onClick={toggleLang}
              className="rounded-full px-2 py-1 text-xs font-medium text-muted-foreground hover:bg-accent hover:text-foreground"
            >
              {i18n.language === "zh" ? "EN" : "\u4e2d"}
            </button>

            <button
              onClick={toggleTheme}
              className="rounded-full p-2 text-muted-foreground hover:bg-accent hover:text-foreground"
              aria-label={theme === "dark" ? t("settings.themeLight") : t("settings.themeDark")}
            >
              {theme === "dark" ? <Sun className="h-5 w-5" /> : <Moon className="h-5 w-5" />}
            </button>

            {user ? (
              <DropdownMenu.Root>
                <DropdownMenu.Trigger asChild>
                  <button className="flex items-center gap-1.5 rounded-full bg-muted px-3 py-1.5 text-sm font-medium text-foreground hover:bg-accent">
                    <span
                      className="flex h-5 w-5 items-center justify-center rounded-full text-[11px] font-bold text-white"
                      style={{ backgroundColor: getUserColor(user.displayName) }}
                    >
                      {user.displayName.charAt(0).toUpperCase()}
                    </span>
                    <span className="hidden sm:inline">{user.displayName}</span>
                  </button>
                </DropdownMenu.Trigger>
                <DropdownMenu.Portal>
                  <DropdownMenu.Content
                    className="z-50 min-w-[160px] rounded-md border border-border bg-card p-1 shadow-lg"
                    sideOffset={8}
                    align="end"
                  >
                    <DropdownMenu.Item
                      className="flex cursor-pointer items-center gap-2 rounded-sm px-3 py-2 text-sm text-foreground outline-none hover:bg-accent"
                      onSelect={() => navigate("/settings")}
                    >
                      <Settings className="h-4 w-4" />
                      {t("nav.settings")}
                    </DropdownMenu.Item>
                    <DropdownMenu.Item
                      className="flex cursor-pointer items-center gap-2 rounded-sm px-3 py-2 text-sm text-foreground outline-none hover:bg-accent"
                      onSelect={() => navigate("/history")}
                    >
                      <History className="h-4 w-4" />
                      {t("nav.history")}
                    </DropdownMenu.Item>
                    {user.role === "admin" && (
                      <DropdownMenu.Item
                        className="flex cursor-pointer items-center gap-2 rounded-sm px-3 py-2 text-sm text-foreground outline-none hover:bg-accent"
                        onSelect={() => navigate("/admin")}
                      >
                        <Shield className="h-4 w-4" />
                        {t("nav.admin")}
                      </DropdownMenu.Item>
                    )}
                    <DropdownMenu.Separator className="my-1 h-px bg-border" />
                    <DropdownMenu.Item
                      className="flex cursor-pointer items-center gap-2 rounded-sm px-3 py-2 text-sm text-destructive outline-none hover:bg-accent"
                      onSelect={() => void handleLogout()}
                    >
                      <LogOut className="h-4 w-4" />
                      {t("nav.logout")}
                    </DropdownMenu.Item>
                  </DropdownMenu.Content>
                </DropdownMenu.Portal>
              </DropdownMenu.Root>
            ) : (
              <button
                onClick={() => navigate("/login")}
                className="flex items-center gap-1.5 rounded-full bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground"
              >
                <LogIn className="h-4 w-4" />
                <span className="hidden sm:inline">{t("nav.login")}</span>
              </button>
            )}
          </div>
        </div>

      </div>
    </header>
  );
}
