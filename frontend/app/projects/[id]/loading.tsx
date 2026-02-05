export default function ProjectDetailLoading() {
  return (
    <div className="h-full flex flex-col">
      {/* Tab bar skeleton */}
      <div className="border-b border-slate-700 px-4">
        <div className="flex items-center gap-4 py-3">
          {[1, 2, 3, 4].map((i) => (
            <div
              key={i}
              className="h-8 w-24 bg-slate-800 rounded animate-pulse"
            />
          ))}
        </div>
      </div>

      {/* Content skeleton */}
      <div className="flex-1 p-4 space-y-4">
        {/* Stats row */}
        <div className="grid grid-cols-4 gap-4">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="card p-4">
              <div className="h-4 w-16 bg-slate-800/50 rounded animate-pulse mb-2" />
              <div className="h-8 w-24 bg-slate-800 rounded animate-pulse" />
            </div>
          ))}
        </div>

        {/* Main content area */}
        <div className="card p-6 space-y-4">
          <div className="h-6 w-48 bg-slate-800 rounded animate-pulse" />
          <div className="grid grid-cols-3 gap-4">
            {[1, 2, 3, 4, 5, 6].map((i) => (
              <div key={i} className="card-elevated p-4 space-y-3">
                <div className="flex items-center justify-between">
                  <div className="h-4 w-32 bg-slate-800 rounded animate-pulse" />
                  <div className="h-5 w-16 bg-slate-800/50 rounded-full animate-pulse" />
                </div>
                <div className="space-y-2">
                  <div className="h-3 w-full bg-slate-800/30 rounded animate-pulse" />
                  <div className="h-3 w-3/4 bg-slate-800/30 rounded animate-pulse" />
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
