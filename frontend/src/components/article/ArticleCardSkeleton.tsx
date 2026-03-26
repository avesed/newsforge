import { Skeleton } from "@/components/ui/Skeleton";

export function ArticleCardSkeleton() {
  return (
    <div className="border-b border-border/50 last:border-b-0">
      <div className="px-1 py-4 -mx-1">
        {/* Meta row: source + time */}
        <div className="flex items-center gap-2 mb-1.5">
          <Skeleton className="h-3 w-16" />
          <Skeleton className="h-3 w-20" />
        </div>

        {/* Title: 2 lines */}
        <div className="mb-1 space-y-1.5">
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-3/4" />
        </div>

        {/* Summary: 1 line */}
        <Skeleton className="h-3.5 w-5/6 mb-2" />

        {/* Tags row: 2 pills */}
        <div className="flex items-center gap-1.5">
          <Skeleton className="h-5 w-14 rounded-full" />
          <Skeleton className="h-5 w-16 rounded-full" />
        </div>
      </div>
    </div>
  );
}

export function ArticleListSkeleton({ count = 6 }: { count?: number }) {
  return (
    <div className="flex flex-col">
      {Array.from({ length: count }, (_, i) => (
        <ArticleCardSkeleton key={i} />
      ))}
    </div>
  );
}
