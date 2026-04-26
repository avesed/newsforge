import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { BarChart3, Rss, Key, Cpu, Zap, Shield, Import, Users } from "lucide-react";
import type { LucideIcon } from "lucide-react";

interface NavItem {
  path: string;
  label: string;
  icon: LucideIcon;
  exact?: boolean;
}

const NAV_ITEMS: NavItem[] = [
  { path: "/admin", label: "admin.overview", icon: BarChart3, exact: true },
  { path: "/admin/feeds", label: "admin.feeds", icon: Rss },
  { path: "/admin/consumers", label: "admin.consumers", icon: Key },
  { path: "/admin/llm", label: "admin.llm", icon: Cpu },
  { path: "/admin/pipeline", label: "admin.pipeline", icon: Zap },
  { path: "/admin/users", label: "admin.users", icon: Users },
  { path: "/admin/import", label: "admin.import.nav", icon: Import },
];

export function AdminLayout({ children }: { children: ReactNode }) {
  const { t } = useTranslation();

  return (
    <div className="flex flex-col gap-4">
      {/* Page title */}
      <div className="flex items-center gap-2">
        <Shield className="h-6 w-6 text-primary" />
        <h1 className="text-2xl font-bold text-foreground">
          {t("admin.title")}
        </h1>
      </div>

      <div className="flex flex-col gap-4 lg:flex-row lg:gap-6">
        {/* Sidebar: desktop left column, mobile horizontal scroll pills */}
        <nav className="flex gap-1 overflow-x-auto lg:w-48 lg:shrink-0 lg:flex-col">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.path}
              to={item.path}
              end={item.exact === true ? true : false}
              className={({ isActive }) =>
                `flex items-center gap-2 rounded-md px-3 py-2 text-sm whitespace-nowrap ${
                  isActive
                    ? "bg-primary/10 text-primary font-medium"
                    : "text-muted-foreground hover:bg-muted"
                }`
              }
            >
              <item.icon className="h-4 w-4" />
              {t(item.label)}
            </NavLink>
          ))}
        </nav>

        {/* Main content */}
        <div className="flex-1 min-w-0">{children}</div>
      </div>
    </div>
  );
}
