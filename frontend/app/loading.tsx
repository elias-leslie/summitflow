export default function Loading() {
  return (
    <div className="flex items-center justify-center h-full min-h-[400px]">
      <div className="flex flex-col items-center gap-4">
        {/* Animated spinner with outrun theme */}
        <div className="relative">
          <div className="w-12 h-12 border-2 border-outrun-500/20 rounded-full" />
          <div className="absolute inset-0 w-12 h-12 border-2 border-transparent border-t-outrun-500 rounded-full animate-spin" />
        </div>
        <p className="text-sm text-slate-400 animate-pulse">Loading...</p>
      </div>
    </div>
  )
}
