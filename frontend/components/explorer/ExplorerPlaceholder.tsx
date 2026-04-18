/**
 * ExplorerPlaceholder - Placeholder content when no children provided
 */

import { typeIcons, typeTitles } from './explorerConstants'
import type { ExplorerType } from './types'

interface ExplorerPlaceholderProps {
  type: ExplorerType
}

export function ExplorerPlaceholder({ type }: ExplorerPlaceholderProps) {
  return (
    <div className="flex flex-col items-center justify-center h-full text-slate-500">
      <div className="opacity-20 mb-4">{typeIcons[type]}</div>
      <p className="text-sm">{typeTitles[type]} content will render here</p>
      <p className="text-xs text-slate-600 mt-1">
        Connect data source to display items
      </p>
    </div>
  )
}
