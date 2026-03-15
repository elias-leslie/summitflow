'use client'

import { useState } from 'react'
import { ArrowRight, CheckCircle2, HardDrive, Loader2, Wifi, XCircle } from 'lucide-react'
import Link from 'next/link'
import { type StorageBackend, type StorageStatus, testStorageBackend } from '@/lib/api/backups'

interface StorageCardProps {
  backends: StorageBackend[]
  storageStatus: StorageStatus | undefined
  onRefresh: () => void
}

export function StorageCard({ backends, storageStatus, onRefresh }: StorageCardProps) {
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null)

  const configured = storageStatus?.configured ?? false
  const defaultBackend = backends.find((b) => b.is_default) ?? backends[0]

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
    <div className="bg-slate-800/50 rounded-lg border border-slate-700 p-4">
      <div className="flex items-center gap-2 mb-3">
        <HardDrive className="w-4 h-4 text-slate-400" />
        <h3 className="text-sm font-medium text-slate-200">Storage Backend</h3>
        {configured && (
          <span className="text-xs text-green-400 ml-auto">Connected</span>
        )}
      </div>

      {configured && defaultBackend ? (
        <>
          <div className="flex items-center gap-2 mb-2">
            <span className="text-sm text-slate-300">{defaultBackend.name}</span>
            <span className="text-xs px-1.5 py-0.5 rounded bg-blue-500/15 text-blue-400">
              {defaultBackend.backend_type.toUpperCase()}
            </span>
            {backends.length > 1 && (
              <span className="text-xs text-slate-500">
                +{backends.length - 1} more
              </span>
            )}
          </div>

          {/* Config details */}
          {defaultBackend.config && (
            <div className="text-xs text-slate-500 mb-3 space-y-0.5">
              {(defaultBackend.config as Record<string, string>).host && (
                <div>
                  {(defaultBackend.config as Record<string, string>).host}
                  {(defaultBackend.config as Record<string, string>).share &&
                    `/${(defaultBackend.config as Record<string, string>).share}`}
                </div>
              )}
            </div>
          )}

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleTest}
              disabled={testing}
              className="flex items-center gap-1.5 px-2.5 py-1 text-xs rounded bg-slate-700 text-slate-300 hover:bg-slate-600 transition-colors disabled:opacity-50"
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
              className="flex items-center gap-1 text-xs text-phosphor-400 hover:text-phosphor-300 transition-colors"
            >
              Manage
              <ArrowRight className="w-3 h-3" />
            </Link>
          </div>

          {testResult && (
            <div className="flex items-center gap-1.5 mt-2">
              {testResult.success ? (
                <CheckCircle2 className="w-3.5 h-3.5 text-green-400" />
              ) : (
                <XCircle className="w-3.5 h-3.5 text-red-400" />
              )}
              <span
                className={`text-xs ${testResult.success ? 'text-green-400' : 'text-red-400'}`}
              >
                {testResult.message}
              </span>
            </div>
          )}
        </>
      ) : (
        <>
          <p className="text-xs text-slate-400 mb-3">
            Configure where backups are stored. Without a storage backend, backups
            are only kept locally.
          </p>
          <Link
            href="/backups/setup"
            className="inline-flex items-center gap-2 px-3 py-1.5 bg-phosphor-600 text-white rounded-md text-xs font-medium hover:bg-phosphor-500 transition-colors"
          >
            Set up storage
            <ArrowRight className="w-3 h-3" />
          </Link>
        </>
      )}
    </div>
  )
}
