import { Skeleton } from '@/components/ui/skeleton'

export function ProjectCardGridSkeleton() {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      {Array.from({ length: 6 }).map((_, index) => (
        <div key={index} className="card p-5 space-y-4">
          <div className="flex items-center gap-3">
            <Skeleton className="w-12 h-12 rounded-xl" />
            <div className="space-y-2 flex-1">
              <Skeleton className="h-4 w-3/4 rounded" />
              <Skeleton className="h-3 w-1/2 rounded" />
            </div>
          </div>
          <Skeleton className="h-px w-full" />
          <div className="flex items-center gap-3">
            <Skeleton className="h-6 w-12 rounded" />
            <Skeleton className="h-6 w-12 rounded" />
            <Skeleton className="h-6 w-12 rounded" />
          </div>
        </div>
      ))}
    </div>
  )
}
