import { create } from "zustand";
import type { Category } from "@/types";
import { ALL_CATEGORIES } from "@/types";

interface CategoryState {
  categories: Category[];
  activeCategory: string | null;
}

interface CategoryActions {
  setActiveCategory: (slug: string | null) => void;
  getCategoryBySlug: (slug: string) => Category | undefined;
}

export const useCategoryStore = create<CategoryState & CategoryActions>((set, get) => ({
  categories: ALL_CATEGORIES,
  activeCategory: null,

  setActiveCategory: (slug) => set({ activeCategory: slug }),

  getCategoryBySlug: (slug) => get().categories.find((c) => c.slug === slug),
}));
