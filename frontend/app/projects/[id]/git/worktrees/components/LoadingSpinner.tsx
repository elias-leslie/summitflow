export function LoadingSpinner() {
  return (
    <div className="flex items-center justify-center h-[calc(100vh-6rem)]">
      <div className="w-8 h-8 border-2 border-outrun-500/30 border-t-outrun-500 rounded-full animate-spin" />
    </div>
  )
}
