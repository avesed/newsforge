import { Skeleton } from "@/components/ui/Skeleton";

function StoryCardSkeleton() {
  return (
    <div className="rounded-lg border border-border bg-card p-3">
      <div className="flex items-start gap-2">
        {/* BookOpen icon placeholder */}
        <Skeleton className="mt-0.5 h-4 w-4 flex-shrink-0 rounded" />
        <div className="min-w-0 flex-1">
          {/* Title */}
          <Skeleton className="h-4 w-full" />
          {/* Status badge */}
          <div className="mt-1.5 flex items-center gap-2">
            <Skeleton className="h-3 w-16" />
            <Skeleton className="h-3 w-12" />
          </div>
          {/* Categories + sentiment */}
          <div className="mt-1.5 flex items-center gap-2">
            <Skeleton className="h-4 w-10 rounded-full" />
            <Skeleton className="h-4 w-10 rounded-full" />
            <Skeleton className="h-3 w-8" />
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

export function TrendingStoriesSkeleton() {
  return (
    <section>
      {/* Section title: icon + title bar */}
      <div className="mb-3 flex items-center gap-2">
        <Skeleton className="h-5 w-5 rounded" />
        <Skeleton className="h-5 w-28" />
      </div>
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        <StoryCardSkeleton />
        <StoryCardSkeleton />
        <StoryCardSkeleton />
      </div>
    </section>
  );
}
