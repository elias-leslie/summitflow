'use client'

import { useState } from 'react'
import { CheckCircle2, XCircle, Loader2, HardDrive, Star, Wifi } from 'lucide-react'
import { clsx } from 'clsx'
import { type StorageBackend, testStorageBackend } from '@/lib/api/backups'
import { formatDate } from '@/lib/format'

interface StorageBackendCardProps {
  backend: StorageBackend
  onRefresh?: () => void
}

export function StorageBackendCard({ backend, onRefresh }: StorageBackendCardProps) {
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null)

  const handleTest = async () => {
    setTesting(true)
    setTestResult(null)
    try {
      const result = await testStorageBackend(backend.id)
      setTestResult(result)
      onRefresh?.()
    } catch {
      setTestResult({ success: false, message: 'Test request failed' })
    } finally {
      setTesting(false)
    }
  }

  const config = backend.config as Record<string, string>
  const testStatus = testResult?.success ?? backend.last_test_ok

  return (
    <div
      className={clsx(
        'p-4 rounded-lg border transition-colors',
        backend.enabled
          ? 'bg-slate-800/50 border-slate-700'
          : 'bg-slate-800/30 border-slate-700/50 opacity-60',
      )}
    >
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-2">
          <HardDrive className="w-4 h-4 text-slate-400" />
          <span className="text-sm font-medium text-slate-200">{backend.name}</span>
          {backend.is_default && (
            <span className="flex items-center gap-1 text-[10px] text-amber-400 bg-amber-500/15 px-1.5 py-0.5 rounded border border-amber-500/25">
              <Star className="w-2.5 h-2.5" />
              default
            </span>
          )}
        </div>
        <div className="flex items-center gap-1.5">
          {testStatus != null && (
            testStatus ? (
              <CheckCircle2 className="w-4 h-4 text-green-400" />
            ) : (
              <XCircle className="w-4 h-4 text-red-400" />
            )
          )}
          <span
            className={clsx(
              'text-xs px-2 py-0.5 rounded-full',
              backend.backend_type === 'smb'
                ? 'bg-blue-500/15 text-blue-400'
                : 'bg-slate-600 text-slate-400',
            )}
          >
            {backend.backend_type.toUpperCase()}
          </span>
        </div>
      </div>

      <div className="space-y-1 text-xs text-slate-400 mb-3">
        {config.host && (
          <div>
            <span className="text-slate-500">Host: </span>
            <span className="text-slate-300">{config.host}</span>
          </div>
        )}
        {config.share && (
          <div>
            <span className="text-slate-500">Share: </span>
            <span className="text-slate-300">{config.share}</span>
          </div>
        )}
        {config.path && (
          <div>
            <span className="text-slate-500">Path: </span>
            <span className="text-slate-300">{config.path}</span>
          </div>
        )}
        {backend.last_test_at && (
          <div>
            <span className="text-slate-500">Last tested: </span>
            <span className="text-slate-300">{formatDate(backend.last_test_at)}</span>
          </div>
        )}
      </div>

      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={handleTest}
          disabled={testing}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-md
                     bg-slate-700 text-slate-300 hover:bg-slate-600 transition-colors
                     disabled:opacity-50"
        >
          {testing ? (
            <Loader2 className="w-3 h-3 animate-spin" />
          ) : (
            <Wifi className="w-3 h-3" />
          )}
          {testing ? 'Testing...' : 'Test Connection'}
        </button>
      </div>

      {testResult && (
        <p
          className={clsx(
            'mt-2 text-xs',
            testResult.success ? 'text-green-400' : 'text-red-400',
          )}
        >
          {testResult.message}
        </p>
      )}
    </div>
  )
}
