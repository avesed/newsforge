import { useEffect } from "react";
import { CategoryNav } from "@/components/category/CategoryNav";
import { CategorySidebar } from "@/components/category/CategorySidebar";
import { ArticleList } from "@/components/article/ArticleList";
import { TrendingStories } from "@/components/stories/TrendingStories";
import { useCategoryStore } from "@/stores/categoryStore";

export default function HomePage() {
  const { activeCategory, setActiveCategory } = useCategoryStore();

  useEffect(() => {
    setActiveCategory(null);
  }, [setActiveCategory]);

  return (
    <div className="flex gap-6">
      {/* Sidebar - desktop only */}
      <div className="hidden lg:block">
        <CategorySidebar
          activeCategory={activeCategory}
          onSelect={(slug) => setActiveCategory(slug)}
        />
      </div>

      {/* Main content */}
      <div className="flex-1 min-w-0 flex flex-col gap-4">
        {/* Mobile category nav (horizontal scroll) */}
        <div className="lg:hidden">
          <CategoryNav
            activeCategory={activeCategory}
            onSelect={(slug) => setActiveCategory(slug)}
          />
        </div>

        <TrendingStories />
        <ArticleList category={activeCategory ?? undefined} />
      </div>
    </div>
  );
}
