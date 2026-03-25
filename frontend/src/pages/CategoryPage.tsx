import { useEffect } from "react";
import { useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { ArticleList } from "@/components/article/ArticleList";
import { useCategoryStore } from "@/stores/categoryStore";

export default function CategoryPage() {
  const { category } = useParams<{ category: string }>();
  const { t } = useTranslation();
  const { setActiveCategory } = useCategoryStore();

  useEffect(() => {
    setActiveCategory(category ?? null);
    return () => setActiveCategory(null);
  }, [category, setActiveCategory]);

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-2xl font-bold text-foreground">
        {category ? t(`category.${category}`, category) : t("category.all")}
      </h1>
      <ArticleList category={category} />
    </div>
  );
}
