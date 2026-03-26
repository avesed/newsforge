import { useTranslation } from "react-i18next";
import { ALL_CATEGORIES, CATEGORY_COLORS, type CategorySlug } from "@/types";
import { cn } from "@/lib/utils";

interface CategorySidebarProps {
  activeCategory: string | null;
  onSelect: (category: string | null) => void;
}

export function CategorySidebar({ activeCategory, onSelect }: CategorySidebarProps) {
  const { t } = useTranslation();

  return (
    <nav className="sticky top-20 w-48 flex-shrink-0">
      <h3 className="mb-3 px-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
        {t("nav.categories")}
      </h3>
      <ul className="flex flex-col gap-0.5">
        {/* All */}
        <li>
          <button
            onClick={() => onSelect(null)}
            className={cn(
              "flex w-full items-center gap-2.5 rounded-md px-3 py-2 text-sm font-medium transition-all duration-150",
              activeCategory === null
                ? "bg-primary/10 text-primary"
                : "text-muted-foreground hover:bg-accent hover:text-foreground"
            )}
          >
            <span
              className="h-2 w-2 rounded-full bg-foreground/40"
            />
            {t("category.all")}
          </button>
        </li>

        {/* Category items */}
        {ALL_CATEGORIES.map((cat) => {
          const isActive = activeCategory === cat.slug;
          const color = CATEGORY_COLORS[cat.slug as CategorySlug] ?? CATEGORY_COLORS.other;
          return (
            <li key={cat.slug}>
              <button
                onClick={() => onSelect(cat.slug)}
                className={cn(
                  "flex w-full items-center gap-2.5 rounded-md px-3 py-2 text-sm font-medium transition-all duration-150",
                  isActive
                    ? "bg-primary/10 text-primary"
                    : "text-muted-foreground hover:bg-accent hover:text-foreground"
                )}
              >
                <span
                  className="h-2 w-2 rounded-full flex-shrink-0"
                  style={{ backgroundColor: color }}
                />
                {t(`category.${cat.slug}`)}
              </button>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
