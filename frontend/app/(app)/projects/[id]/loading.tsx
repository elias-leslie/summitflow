import { Skeleton } from '@/components/ui/skeleton'

export default function ProjectDetailLoading() {
  return (
    <div className="h-full flex flex-col">
      {/* Tab bar skeleton */}
      <div className="border-b border-slate-700/50 px-4">
        <div className="flex items-center gap-4 py-3">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-8 w-24 rounded-md" />
          ))}
        </div>
      </div>

      {/* Content skeleton */}
      <div className="flex-1 p-4 space-y-4">
        {/* Toolbar skeleton */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Skeleton className="h-8 w-20 rounded-md" />
            <Skeleton className="h-8 w-20 rounded-md" />
          </div>
          <Skeleton className="h-8 w-28 rounded-md" />
        </div>

        {/* Kanban rows skeleton */}
        {[1, 2, 3].map((row) => (
          <div key={row} className="card p-4 space-y-3">
            <div className="flex items-center gap-2">
              <Skeleton className="h-4 w-4 rounded" />
              <Skeleton className="h-4 w-24 rounded" />
              <Skeleton className="h-5 w-6 rounded-full" />
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
              {Array.from({ length: row === 2 ? 4 : 2 }).map((_, i) => (
                <div key={i} className="card p-3 space-y-2">
                  <div className="flex items-center gap-2">
                    <Skeleton className="h-5 w-14 rounded" />
                    <Skeleton className="h-3 w-3 rounded-full" />
                  </div>
                  <Skeleton className="h-4 w-full rounded" />
                  <Skeleton className="h-3 w-2/3 rounded" />
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
