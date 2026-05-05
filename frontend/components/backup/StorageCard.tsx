'use client'

import { clsx } from 'clsx'
import {
  ArrowRight,
  CheckCircle2,
  FolderOpen,
  Loader2,
  Server,
  Wifi,
  XCircle,
} from 'lucide-react'
import Link from 'next/link'
import { useState } from 'react'
import { CollapsibleSection } from '@/components/backup/CollapsibleSection'
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
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{
    success: boolean
    message: string
  } | null>(null)

  const configured = storageStatus?.configured ?? false
  const defaultBackend = backends.find((b) => b.is_default) ?? backends[0]
  const backendConfig = defaultBackend?.config as
    | Record<string, string>
    | undefined
  const backendLocation =
    defaultBackend?.backend_type === 'local'
      ? [backendConfig?.root_path, backendConfig?.path]
          .filter(Boolean)
          .join('/')
      : backendConfig?.host
        ? `${backendConfig.host}${backendConfig.share ? `/${backendConfig.share}` : ''}`
        : ''
  const summary =
    configured && defaultBackend
      ? `${defaultBackend.name} over ${defaultBackend.backend_type.toUpperCase()}${backendLocation ? ` at ${backendLocation}` : ''}`
      : 'Storage is not configured yet, so backups stay in project-local archives until a backend is connected.'

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
    <CollapsibleSection
      title="Storage"
      titleAccessory={
        <span
          className={clsx(
            'text-[10px] uppercase tracking-[0.14em]',
            configured ? 'text-emerald-400' : 'text-amber-400',
          )}
        >
          {configured ? 'Connected' : 'Local Only'}
        </span>
      }
      summary={summary}
      className="transition-all duration-200"
      expandedClassName="border-slate-700/80 shadow-lg shadow-black/20"
      collapsedClassName="hover:bg-slate-900/50"
      contentClassName="border-t border-slate-800/40 px-4 py-4 space-y-3"
    >
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
                {defaultBackend.backend_type === 'local' ? (
                  <FolderOpen className="w-3 h-3 inline mr-1 text-emerald-400" />
                ) : (
                  <Server className="w-3 h-3 inline mr-1 text-blue-400" />
                )}
                {defaultBackend.backend_type.toUpperCase()}
              </div>
            </div>
            {backendLocation && (
              <div className="min-w-0 rounded bg-slate-950/50 px-2 py-1.5 col-span-2">
                <div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">
                  Location
                </div>
                <div className="truncate text-xs text-slate-200 font-mono">
                  {backendLocation}
                </div>
              </div>
            )}
          </div>

          {backends.length > 1 && (
            <p className="text-2xs text-slate-500">
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
              className="text-2xs px-2 py-1 rounded bg-slate-700/50 text-slate-400 hover:bg-slate-700/80 disabled:opacity-40 transition-colors flex items-center gap-1.5"
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
              className="text-2xs text-phosphor-400 hover:text-phosphor-300 transition-colors flex items-center gap-1"
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
                  testResult.success ? 'text-emerald-400' : 'text-red-400',
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
            backups are kept in project-local archives.
          </p>
          <Link
            href="/backups/setup"
            className="inline-flex items-center gap-1.5 text-2xs px-2.5 py-1 rounded bg-phosphor-500/10 text-phosphor-400 hover:bg-phosphor-500/20 transition-colors"
          >
            Set up storage
            <ArrowRight className="w-3 h-3" />
          </Link>
        </>
      )}
    </CollapsibleSection>
  )
}
