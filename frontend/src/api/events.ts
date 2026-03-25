import apiClient from "./client";
import type { Article } from "@/types";

export interface NewsEvent {
  id: string;
  title: string;
  eventType: string;
  primaryEntity: string | null;
  entityType: string | null;
  categories: string[] | null;
  articleCount: number;
  firstSeenAt: string | null;
  lastUpdatedAt: string | null;
  sentimentAvg: number | null;
  sources: string[] | null;
  representativeTitle: string | null;
  representativeSummary: string | null;
}

export interface EventDetail extends NewsEvent {
  articles: Article[];
}

export async function getTrendingEvents(limit = 5): Promise<NewsEvent[]> {
  const response = await apiClient.get<NewsEvent[]>("/events/trending", {
    params: { limit },
  });
  return response.data;
}

export async function getEventDetail(eventId: string): Promise<EventDetail> {
  const response = await apiClient.get<EventDetail>(`/events/${eventId}`);
  return response.data;
}
