export default function Loading() {
  return (
    <div className="flex items-center justify-center h-full min-h-[400px]">
      <div className="flex flex-col items-center gap-5">
        <div className="relative">
          <div className="w-10 h-10 border-2 border-outrun-500/10 rounded-full" />
          <div className="absolute inset-0 w-10 h-10 border-2 border-transparent border-t-outrun-500 rounded-full animate-spin" />
          <div
            className="absolute inset-1 w-8 h-8 border border-transparent border-b-phosphor-500/40 rounded-full animate-spin"
            style={{ animationDirection: 'reverse', animationDuration: '1.5s' }}
          />
        </div>
        <p className="text-sm text-slate-500 tracking-wide font-medium">Loading</p>
      </div>
    </div>
  )
}
