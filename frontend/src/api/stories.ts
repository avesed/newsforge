import apiClient from "./client";
import type { Article } from "@/types";

export interface NewsStory {
  id: string;
  title: string;
  description: string | null;
  storyType: string;
  status: string;
  keyEntities: string[] | null;
  categories: string[] | null;
  articleCount: number;
  firstSeenAt: string | null;
  lastUpdatedAt: string | null;
  sentimentAvg: number | null;
  representativeTitle: string | null;
  representativeSummary: string | null;
}

export interface TimelineEntry {
  date: string;
  summary: string;
}

export interface StoryDetail extends NewsStory {
  articles: Article[];
  timeline: TimelineEntry[] | null;
}

export async function getTrendingStories(limit = 10): Promise<NewsStory[]> {
  const response = await apiClient.get<NewsStory[]>("/stories/trending", {
    params: { limit },
  });
  return response.data;
}

export async function getStoryDetail(storyId: string): Promise<StoryDetail> {
  const response = await apiClient.get<StoryDetail>(`/stories/${storyId}`);
  return response.data;
}
