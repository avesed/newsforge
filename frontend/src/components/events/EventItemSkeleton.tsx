import { Skeleton } from "@/components/ui/Skeleton";

function EventCardSkeleton() {
  return (
    <div className="rounded-lg border border-border bg-card p-3">
      <div className="flex items-start gap-2">
        {/* Flame icon placeholder */}
        <Skeleton className="mt-0.5 h-4 w-4 flex-shrink-0 rounded" />
        <div className="min-w-0 flex-1">
          {/* Title */}
          <Skeleton className="h-4 w-full" />
          {/* Meta row */}
          <div className="mt-1 flex items-center gap-2">
            <Skeleton className="h-3 w-12" />
            <Skeleton className="h-4 w-10 rounded-full" />
            <Skeleton className="h-4 w-10 rounded-full" />
          </div>
        </div>
      </div>
    </div>
  );
}

export function TrendingEventsSkeleton() {
  return (
    <section>
      {/* Section title: icon + title bar */}
      <div className="mb-3 flex items-center gap-2">
        <Skeleton className="h-5 w-5 rounded" />
        <Skeleton className="h-5 w-28" />
      </div>
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        <EventCardSkeleton />
        <EventCardSkeleton />
        <EventCardSkeleton />
      </div>
    </section>
  );
}
