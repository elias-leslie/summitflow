'use client'

import clsx from 'clsx'
import { CheckCircle2, ChevronDown, ChevronRight, XCircle } from 'lucide-react'
import { useState } from 'react'
import type { publishProjectChanges } from '@/lib/api'

type PublishResult =
  ReturnType<typeof publishProjectChanges> extends Promise<infer T> ? T : never

export function PublishResultBlock({ result }: { result: PublishResult }) {
  const [showLog, setShowLog] = useState(false)

  return (
    <div
      className={clsx(
        'mt-3 rounded-md border p-3',
        result.success
          ? 'bg-emerald-500/5 border-emerald-500/20'
          : 'bg-pink-500/5 border-pink-500/20',
      )}
    >
      <div className="flex items-center gap-2 mb-1.5">
        {result.success ? (
          <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
        ) : (
          <XCircle className="w-3.5 h-3.5 text-pink-500" />
        )}
        <span
          className={clsx(
            'text-xs font-medium',
            result.success ? 'text-emerald-400' : 'text-pink-400',
          )}
        >
          {result.reason === 'pushed_existing'
            ? 'PUSHED'
            : result.reason === 'no_changes'
              ? 'SKIP'
              : result.status}
        </span>
        {result.pushed && (
          <span className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">
            PUSHED
          </span>
        )}
      </div>
      {result.gates && (
        <div className="flex flex-wrap gap-1 mb-1.5">
          {result.gates
            .split('|')
            .filter(Boolean)
            .map((gate) => {
              const [name, status] = gate.split(':')
              const passed = status === 'PASS' || status === 'SKIP'
              const isWarn = status?.startsWith('WARN')
              return (
                <span
                  key={gate}
                  className={clsx(
                    'text-[9px] font-mono px-1 py-0.5 rounded border inline-flex items-center gap-0.5',
                    passed
                      ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
                      : isWarn
                        ? 'bg-amber-500/10 text-amber-400 border-amber-500/20'
                        : 'bg-pink-500/10 text-pink-400 border-pink-500/20',
                  )}
                >
                  <span
                    className={clsx(
                      'w-1 h-1 rounded-full',
                      passed
                        ? 'bg-emerald-400'
                        : isWarn
                          ? 'bg-amber-400'
                          : 'bg-pink-400',
                    )}
                  />
                  {name}
                </span>
              )
            })}
        </div>
      )}
      {result.errors.length > 0 && (
        <div className="space-y-0.5 mb-1.5">
          {result.errors.map((error, index) => (
            <div
              key={`${error}-${index}`}
              className="text-[10px] font-mono text-pink-400 bg-pink-500/5 px-2 py-0.5 rounded"
            >
              {error}
            </div>
          ))}
        </div>
      )}
      {result.message && (
        <div className="text-[10px] font-mono text-slate-400 bg-slate-950/50 px-2 py-1 rounded border border-slate-800 mb-1.5">
          <span className="text-purple-400">$</span> {result.message}
        </div>
      )}
      <button
        type="button"
        onClick={() => setShowLog(!showLog)}
        className="flex items-center gap-1 text-[9px] text-slate-500 hover:text-slate-300 uppercase tracking-wider"
      >
        {showLog ? (
          <ChevronDown className="w-2.5 h-2.5" />
        ) : (
          <ChevronRight className="w-2.5 h-2.5" />
        )}
        Log
      </button>
      {showLog && (
        <pre className="mt-1.5 text-[9px] font-mono leading-relaxed text-slate-400 bg-slate-950/60 p-2 rounded border border-slate-800 overflow-x-auto max-h-40">
          {result.raw_output}
        </pre>
      )}
    </div>
  )
}
