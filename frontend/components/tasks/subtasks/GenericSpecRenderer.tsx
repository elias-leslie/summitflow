'use client'

import type { SpecRecord } from './SpecRendererTypes'

/** Generic spec renderer as key-value table */
export function GenericSpecRenderer({ spec }: { spec: SpecRecord }) {
  const entries = Object.entries(spec)

  if (entries.length === 0) {
    return <span className="text-2xs text-slate-500">(empty spec)</span>
  }

  return (
    <div className="grid grid-cols-[auto,1fr] gap-x-3 gap-y-1">
      {entries.map(([key, value]) => (
        <div key={key} className="contents">
          <span className="text-2xs text-slate-500 font-mono text-right">
            {key}:
          </span>
          <span className="text-2xs text-amber-300/80 break-all">
            {typeof value === 'string' ? value : JSON.stringify(value, null, 2)}
          </span>
        </div>
      ))}
    </div>
  )
}
