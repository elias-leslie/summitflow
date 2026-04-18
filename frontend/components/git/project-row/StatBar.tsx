export function StatBar({
  additions,
  deletions,
}: {
  additions: number
  deletions: number
}) {
  const total = additions + deletions
  if (total === 0) return null
  const addPct = Math.max(2, (additions / total) * 100)
  const delPct = Math.max(2, (deletions / total) * 100)

  return (
    <div className="flex items-center h-1.5 w-14 rounded-full overflow-hidden bg-slate-800">
      <div
        className="h-full bg-emerald-500 rounded-l-full"
        style={{ width: `${addPct}%` }}
      />
      <div
        className="h-full bg-rose-500 rounded-r-full"
        style={{ width: `${delPct}%` }}
      />
    </div>
  )
}
