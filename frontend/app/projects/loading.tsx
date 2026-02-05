export default function ProjectsLoading() {
  return (
    <div className="p-6 space-y-6">
      {/* Header skeleton */}
      <div className="flex items-center justify-between">
        <div className="space-y-2">
          <div className="h-8 w-48 bg-slate-800 rounded animate-pulse" />
          <div className="h-4 w-64 bg-slate-800/50 rounded animate-pulse" />
        </div>
        <div className="h-10 w-32 bg-slate-800 rounded animate-pulse" />
      </div>

      {/* Content skeleton */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {[1, 2, 3, 4, 5, 6].map((i) => (
          <div key={i} className="card p-6 space-y-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-slate-800 animate-pulse" />
              <div className="space-y-2 flex-1">
                <div className="h-5 w-3/4 bg-slate-800 rounded animate-pulse" />
                <div className="h-3 w-1/2 bg-slate-800/50 rounded animate-pulse" />
              </div>
            </div>
            <div className="space-y-2">
              <div className="h-3 w-full bg-slate-800/30 rounded animate-pulse" />
              <div className="h-3 w-2/3 bg-slate-800/30 rounded animate-pulse" />
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
