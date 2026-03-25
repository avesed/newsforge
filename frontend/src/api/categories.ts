import apiClient from "./client";
import type { Category } from "@/types";

export async function getCategories(): Promise<Category[]> {
  const response = await apiClient.get<Category[]>("/categories");
  return response.data;
}
