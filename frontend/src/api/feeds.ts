import apiClient from "./client";
import type { Feed } from "@/types";

export async function getFeeds(): Promise<Feed[]> {
  const response = await apiClient.get<Feed[]>("/feeds");
  return response.data;
}

export async function createFeed(data: {
  name: string;
  url: string;
  category: string;
}): Promise<Feed> {
  const response = await apiClient.post<Feed>("/feeds", data);
  return response.data;
}

export async function deleteFeed(id: string): Promise<void> {
  await apiClient.delete(`/feeds/${id}`);
}

export async function toggleFeed(id: string, isEnabled: boolean): Promise<Feed> {
  const response = await apiClient.patch<Feed>(`/feeds/${id}`, { isEnabled });
  return response.data;
}
