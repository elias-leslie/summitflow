import { ProjectCardGridSkeleton } from '@/components/projects/ProjectCardGridSkeleton'
import { Skeleton } from '@/components/ui/skeleton'

export default function ProjectsLoading() {
  return (
    <div className="p-6 space-y-6">
      {/* Header skeleton */}
      <div className="flex items-center justify-between">
        <div className="space-y-2">
          <Skeleton className="h-8 w-48 rounded" />
          <Skeleton className="h-4 w-64 rounded" />
        </div>
        <Skeleton className="h-10 w-32 rounded-md" />
      </div>

      {/* Content skeleton */}
      <ProjectCardGridSkeleton />
    </div>
  )
}
