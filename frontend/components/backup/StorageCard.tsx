'use client'

import { useState } from 'react'
import { clsx } from 'clsx'
import {
  ArrowRight,
  CheckCircle2,
  ChevronRight,
  HardDrive,
  Loader2,
  Wifi,
  XCircle,
} from 'lucide-react'
import Link from 'next/link'
import {
  type StorageBackend,
  type StorageStatus,
  testStorageBackend,
} from '@/lib/api/backups'

interface StorageCardProps {
  backends: StorageBackend[]
  storageStatus: StorageStatus | undefined
  onRefresh: () => void
}

export function StorageCard({
  backends,
  storageStatus,
  onRefresh,
}: StorageCardProps) {
  const [expanded, setExpanded] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{
    success: boolean
    message: string
  } | null>(null)

  const configured = storageStatus?.configured ?? false
  const defaultBackend = backends.find((b) => b.is_default) ?? backends[0]

  const accentClass = configured
    ? 'border-l-emerald-500'
    : 'border-l-slate-600'

  const handleTest = async () => {
    if (!defaultBackend) return
    setTesting(true)
    setTestResult(null)
    try {
      const result = await testStorageBackend(defaultBackend.id)
      setTestResult(result)
      onRefresh()
    } catch {
      setTestResult({ success: false, message: 'Test request failed' })
    }
    setTesting(false)
  }

  return (
    <div
      className={clsx(
        'rounded-lg border-l-[3px] border border-slate-700/60 bg-slate-800/40 overflow-hidden transition-all duration-200',
        accentClass,
        expanded
          ? 'border-slate-700/80 shadow-lg shadow-black/20'
          : 'hover:bg-slate-800/60',
      )}
    >
      {/* Header */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-slate-800/30"
      >
        <ChevronRight
          className={clsx(
            'w-3.5 h-3.5 text-slate-600 transition-transform duration-200 shrink-0',
            expanded && 'rotate-90',
          )}
        />
        <div
          className={clsx(
            'w-2 h-2 rounded-full shrink-0',
            configured ? 'bg-emerald-500' : 'bg-slate-600',
          )}
        />
        <HardDrive className="w-3.5 h-3.5 text-slate-500 shrink-0" />
        <span className="text-sm font-medium text-white">Storage Backend</span>
        <span className="text-xs text-slate-500 flex-1 text-right">
          {configured ? 'Connected' : 'Not configured'}
        </span>
      </button>

      {/* Expandable content */}
      <div
        className={clsx(
          'grid transition-all duration-200 ease-out',
          expanded
            ? 'grid-rows-[1fr] opacity-100'
            : 'grid-rows-[0fr] opacity-0',
        )}
      >
        <div className="overflow-hidden">
          <div className="border-t border-slate-800/40 px-4 py-4 space-y-3">
            {configured && defaultBackend ? (
              <>
                {/* Backend details */}
                <div className="grid grid-cols-2 gap-1.5">
                  <div className="min-w-0 rounded bg-slate-950/50 px-2 py-1.5">
                    <div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">
                      Name
                    </div>
                    <div className="truncate text-xs text-slate-200">
                      {defaultBackend.name}
                    </div>
                  </div>
                  <div className="min-w-0 rounded bg-slate-950/50 px-2 py-1.5">
                    <div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">
                      Type
                    </div>
                    <div className="truncate text-xs text-slate-200">
                      {defaultBackend.backend_type.toUpperCase()}
                    </div>
                  </div>
                  {(defaultBackend.config as Record<string, string>)?.host && (
                    <div className="min-w-0 rounded bg-slate-950/50 px-2 py-1.5 col-span-2">
                      <div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">
                        Host
                      </div>
                      <div className="truncate text-xs text-slate-200 font-mono">
                        {(defaultBackend.config as Record<string, string>).host}
                        {(defaultBackend.config as Record<string, string>)
                          .share &&
                          `/${(defaultBackend.config as Record<string, string>).share}`}
                      </div>
                    </div>
                  )}
                </div>

                {backends.length > 1 && (
                  <p className="text-[11px] text-slate-500">
                    +{backends.length - 1} more backend
                    {backends.length > 2 ? 's' : ''}
                  </p>
                )}

                {/* Actions */}
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={handleTest}
                    disabled={testing}
                    className="text-[11px] px-2 py-1 rounded bg-slate-700/50 text-slate-400 hover:bg-slate-700/80 disabled:opacity-40 transition-colors flex items-center gap-1.5"
                  >
                    {testing ? (
                      <Loader2 className="w-3 h-3 animate-spin" />
                    ) : (
                      <Wifi className="w-3 h-3" />
                    )}
                    Test
                  </button>
                  <Link
                    href="/backups/storage"
                    className="text-[11px] text-phosphor-400 hover:text-phosphor-300 transition-colors flex items-center gap-1"
                  >
                    Manage
                    <ArrowRight className="w-3 h-3" />
                  </Link>
                </div>

                {testResult && (
                  <div className="flex items-center gap-1.5">
                    {testResult.success ? (
                      <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                    ) : (
                      <XCircle className="w-3.5 h-3.5 text-red-400" />
                    )}
                    <span
                      className={clsx(
                        'text-xs',
                        testResult.success
                          ? 'text-emerald-400'
                          : 'text-red-400',
                      )}
                    >
                      {testResult.message}
                    </span>
                  </div>
                )}
              </>
            ) : (
              <>
                <p className="text-xs text-slate-400 leading-relaxed">
                  Configure where backups are stored. Without a storage backend,
                  backups are only kept locally.
                </p>
                <Link
                  href="/backups/setup"
                  className="inline-flex items-center gap-1.5 text-[11px] px-2.5 py-1 rounded bg-phosphor-500/10 text-phosphor-400 hover:bg-phosphor-500/20 transition-colors"
                >
                  Set up storage
                  <ArrowRight className="w-3 h-3" />
                </Link>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
