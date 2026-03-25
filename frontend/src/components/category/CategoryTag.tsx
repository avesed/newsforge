import { useTranslation } from "react-i18next";
import { CATEGORY_COLORS, type CategorySlug } from "@/types";

interface CategoryTagProps {
  category: string;
  size?: "sm" | "md";
}

export function CategoryTag({ category, size = "sm" }: CategoryTagProps) {
  const { t } = useTranslation();
  const color = CATEGORY_COLORS[category as CategorySlug] ?? CATEGORY_COLORS.other;
  const label = t(`category.${category}`, category);

  return (
    <span
      className={`inline-flex items-center rounded-full font-medium ${
        size === "sm" ? "px-2 py-0.5 text-xs" : "px-3 py-1 text-sm"
      }`}
      style={{
        backgroundColor: `${color}20`,
        color: color,
      }}
    >
      {label}
    </span>
  );
}
