'use client'

import { Zap } from 'lucide-react'
import type { SyncResult } from '@/lib/api'

interface GitSyncToastProps {
  results: SyncResult[]
}

export function GitSyncToast({ results }: GitSyncToastProps) {
  return (
    <div className="fixed top-20 right-6 z-50 animate-slide-up">
      <div className="card p-4 border border-phosphor-500/30 shadow-[0_0_20px_rgba(0,245,255,0.2)]">
        <div className="flex items-center gap-3 mb-2">
          <Zap className="w-5 h-5 text-phosphor-500" />
          <span className="font-semibold text-white">Sync Complete</span>
        </div>
        <div className="space-y-1 text-sm">
          {results.map((result) => (
            <div
              key={result.path}
              className="flex items-center gap-2 text-slate-300"
            >
              <span className="mono text-xs text-slate-500">{result.name}</span>
              <span
                className={
                  result.status === 'updated'
                    ? 'text-phosphor-500'
                    : result.status === 'skipped'
                      ? 'text-amber-400'
                      : result.status === 'failed'
                        ? 'text-rose-400'
                        : 'text-slate-400'
                }
              >
                {result.status === 'up_to_date' ? 'Up to date' : result.status}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
