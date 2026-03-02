export function highlightText(text: string, searchTerm?: string): React.ReactNode {
  if (!searchTerm || !text) return text
  const regex = new RegExp(`(${searchTerm.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi')
  const parts = text.split(regex)
  return parts.map((part, i) =>
    regex.test(part) ? (
      <mark key={i} className="bg-amber-500/40 text-amber-200 rounded px-0.5">
        {part}
      </mark>
    ) : (
      part
    ),
  )
}

export function formatTokens(tokens: number | null): string {
  if (!tokens) return ''
  if (tokens > 1000) return `${(tokens / 1000).toFixed(1)}k`
  return tokens.toString()
}
