import { Skeleton } from "@/components/ui/Skeleton";

export function ArticlePageSkeleton() {
  return (
    <article className="mx-auto max-w-[720px]">
      {/* Sticky top bar: back button + source link */}
      <div className="sticky top-0 z-10 -mx-4 mb-6 flex items-center justify-between border-b border-border bg-background/95 px-4 py-3 backdrop-blur supports-[backdrop-filter]:bg-background/80">
        <Skeleton className="h-5 w-16" />
        <Skeleton className="h-8 w-28 rounded-md" />
      </div>

      {/* Title: 2 large lines */}
      <div className="mb-4 space-y-2">
        <Skeleton className="h-7 w-full" />
        <Skeleton className="h-7 w-4/5" />
      </div>

      {/* Meta row: 3 bars */}
      <div className="flex items-center gap-3 mb-4">
        <Skeleton className="h-4 w-20" />
        <Skeleton className="h-4 w-24" />
        <Skeleton className="h-4 w-16" />
      </div>

      {/* Category tags: 2 pills */}
      <div className="flex items-center gap-1.5 mb-4">
        <Skeleton className="h-5 w-16 rounded-full" />
        <Skeleton className="h-5 w-14 rounded-full" />
      </div>

      {/* Separator */}
      <div className="border-b border-border mb-6" />

      {/* Content: 8 lines of varying width */}
      <div className="space-y-3">
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-11/12" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-4/5" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-10/12" />
        <Skeleton className="h-4 w-3/5" />
      </div>
    </article>
  );
}
