import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { ALL_CATEGORIES, CATEGORY_COLORS, type CategorySlug } from "@/types";

interface CategoryNavProps {
  activeCategory?: string | null;
  onSelect?: (slug: string | null) => void;
}

export function CategoryNav({ activeCategory, onSelect }: CategoryNavProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const handleSelect = (slug: string | null) => {
    if (onSelect) {
      onSelect(slug);
    } else if (slug === null) {
      navigate("/");
    } else {
      navigate(`/news/${slug}`);
    }
  };

  return (
    <nav className="scrollbar-hide flex gap-2 overflow-x-auto py-2">
      <button
        onClick={() => handleSelect(null)}
        className={`whitespace-nowrap rounded-full px-4 py-1.5 text-sm font-medium transition-colors ${
          activeCategory === null || activeCategory === undefined
            ? "bg-primary text-primary-foreground"
            : "bg-muted text-muted-foreground hover:bg-accent"
        }`}
      >
        {t("category.all")}
      </button>
      {ALL_CATEGORIES.map((cat) => {
        const isActive = activeCategory === cat.slug;
        const color = CATEGORY_COLORS[cat.slug as CategorySlug] ?? CATEGORY_COLORS.other;
        return (
          <button
            key={cat.slug}
            onClick={() => handleSelect(cat.slug)}
            className={`whitespace-nowrap rounded-full px-4 py-1.5 text-sm font-medium transition-colors ${
              isActive ? "text-white" : "text-muted-foreground hover:bg-accent"
            }`}
            style={
              isActive
                ? { backgroundColor: color }
                : { backgroundColor: `${color}15` }
            }
          >
            {t(`category.${cat.slug}`)}
          </button>
        );
      })}
    </nav>
  );
}
