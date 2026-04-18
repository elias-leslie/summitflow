'use client'

import clsx from 'clsx'
import { Globe } from 'lucide-react'
import type { SpecRecord } from './SpecRendererTypes'

/** Method badge for API specs */
function MethodBadge({ method }: { method: string }) {
  const colors: Record<string, string> = {
    GET: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
    POST: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
    PUT: 'bg-amber-500/20 text-amber-400 border-amber-500/30',
    PATCH: 'bg-orange-500/20 text-orange-400 border-orange-500/30',
    DELETE: 'bg-red-500/20 text-red-400 border-red-500/30',
  }
  const colorClass =
    colors[method.toUpperCase()] ||
    'bg-slate-500/20 text-slate-400 border-slate-500/30'

  return (
    <span
      className={clsx(
        'px-1.5 py-0.5 text-2xs font-mono font-semibold rounded border',
        colorClass,
      )}
    >
      {method.toUpperCase()}
    </span>
  )
}

/** API spec renderer with method badge and endpoint */
export function ApiSpecRenderer({ spec }: { spec: SpecRecord }) {
  const method =
    (spec.method as string) || (spec.http_method as string) || 'GET'
  const endpoint =
    (spec.endpoint as string) ||
    (spec.path as string) ||
    (spec.url as string) ||
    (spec.route as string) ||
    ''

  // Extract other fields for additional info
  const otherFields = Object.entries(spec).filter(
    ([key]) =>
      !['method', 'http_method', 'endpoint', 'path', 'url', 'route'].includes(
        key.toLowerCase(),
      ),
  )

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 font-mono">
        <Globe className="w-3.5 h-3.5 text-blue-400" />
        <MethodBadge method={method} />
        <code className="text-xs text-slate-200 bg-slate-800/60 px-2 py-0.5 rounded">
          {endpoint || '(no endpoint)'}
        </code>
      </div>
      {otherFields.length > 0 && (
        <div className="pl-5 space-y-1">
          {otherFields.map(([key, value]) => (
            <div key={key} className="flex gap-2 text-2xs">
              <span className="text-slate-500 font-mono">{key}:</span>
              <span className="text-amber-300/80">
                {typeof value === 'string'
                  ? value
                  : JSON.stringify(value, null, 2)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
