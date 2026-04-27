import type { Ref } from "react";
import { Skeleton } from "@/components/ui/Skeleton";

const CARD_MIN_WIDTH = 320;

function StoryCardSkeleton() {
  return (
    <div className="rounded-lg border border-border bg-card p-3">
      <div className="flex items-start gap-2">
        <Skeleton className="mt-0.5 h-4 w-4 flex-shrink-0 rounded" />
        <div className="min-w-0 flex-1">
          {/* Title */}
          <Skeleton className="h-4 w-full" />
          {/* Summary */}
          <Skeleton className="mt-1 h-3 w-full" />
          <Skeleton className="mt-0.5 h-3 w-3/4" />
          {/* Status + count + categories + time */}
          <div className="mt-1.5 flex items-center gap-2">
            <Skeleton className="h-3 w-16" />
            <Skeleton className="h-3 w-12" />
            <Skeleton className="h-4 w-10 rounded-full" />
            <Skeleton className="h-4 w-10 rounded-full" />
            <Skeleton className="h-3 w-14" />
          </div>
          {/* Key entities */}
          <div className="mt-1.5 flex items-center gap-1.5">
            <Skeleton className="h-4 w-14 rounded" />
            <Skeleton className="h-4 w-14 rounded" />
          </div>
        </div>
      </div>
    </div>
  );
}

interface TrendingStoriesSkeletonProps {
  containerRef?: Ref<HTMLDivElement>;
}

export function TrendingStoriesSkeleton({
  containerRef,
}: TrendingStoriesSkeletonProps) {
  return (
    <section>
      <div className="mb-3 flex items-center gap-2">
        <Skeleton className="h-5 w-5 rounded" />
        <Skeleton className="h-5 w-28" />
      </div>
      <div
        ref={containerRef}
        className="grid gap-2"
        style={{
          gridTemplateColumns: `repeat(auto-fill, minmax(${CARD_MIN_WIDTH}px, 1fr))`,
        }}
      >
        <StoryCardSkeleton />
        <StoryCardSkeleton />
        <StoryCardSkeleton />
      </div>
    </section>
  );
}
