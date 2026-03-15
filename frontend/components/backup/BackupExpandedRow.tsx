'use client'

import { clsx } from 'clsx'
import { Database, FileCheck, HardDrive, ShieldCheck, ShieldX } from 'lucide-react'
import { SourceTypeBadge } from '@/components/backup/SourceTypeBadge'
import { type Backup, type BackupSource, backupHasDatabase } from '@/lib/api/backups'
import { formatBytes, formatDate } from '@/lib/format'

export function BackupExpandedRow({
  backup,
  sourceName,
  sourceType,
}: {
  backup: Backup
  sourceName: string
  sourceType: BackupSource['source_type'] | undefined
}) {
  const hasDatabase = backupHasDatabase(backup)

  return (
    <tr>
      <td colSpan={7} className="px-4 py-0">
        <div className="py-4 pl-6 border-l-2 border-slate-600 ml-2 space-y-3">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
            <div>
              <p className="text-slate-500 text-xs mb-0.5">Source</p>
              <p className="text-slate-200 flex items-center gap-2">
                {sourceName}
                {sourceType && <SourceTypeBadge type={sourceType} />}
              </p>
            </div>
            <div>
              <p className="text-slate-500 text-xs mb-0.5">Type</p>
              <p className="text-slate-200">{backup.backup_type}</p>
            </div>
            <div>
              <p className="text-slate-500 text-xs mb-0.5">Location</p>
              <p className="text-slate-200 truncate">{backup.location || '-'}</p>
            </div>
            <div>
              <p className="text-slate-500 text-xs mb-0.5">Name</p>
              <p className="text-slate-200 font-mono text-xs truncate">{backup.name || '-'}</p>
            </div>
          </div>

          {(hasDatabase || backup.files_size_bytes != null || backup.size_bytes != null) && (
            <div className="flex items-center gap-6 text-sm">
              {hasDatabase && backup.db_size_bytes != null && (
                <div className="flex items-center gap-2">
                  <Database className="w-3.5 h-3.5 text-blue-400" />
                  <span className="text-slate-400">Database:</span>
                  <span className="text-slate-200">{formatBytes(backup.db_size_bytes)}</span>
                </div>
              )}
              {backup.files_size_bytes != null && (
                <div className="flex items-center gap-2">
                  <HardDrive className="w-3.5 h-3.5 text-purple-400" />
                  <span className="text-slate-400">Files:</span>
                  <span className="text-slate-200">{formatBytes(backup.files_size_bytes)}</span>
                </div>
              )}
              {!hasDatabase && (
                <div className="flex items-center gap-2">
                  <HardDrive className="w-3.5 h-3.5 text-purple-400" />
                  <span className="text-slate-400">Backup:</span>
                  <span className="text-slate-200">Files only</span>
                </div>
              )}
            </div>
          )}

          <div className="flex items-center gap-6 text-sm">
            {backup.started_at && (
              <div>
                <span className="text-slate-500">Started: </span>
                <span className="text-slate-300">{formatDate(backup.started_at)}</span>
              </div>
            )}
            {backup.completed_at && (
              <div>
                <span className="text-slate-500">Completed: </span>
                <span className="text-slate-300">{formatDate(backup.completed_at)}</span>
              </div>
            )}
            {backup.started_at && backup.completed_at && (
              <div>
                <span className="text-slate-500">Duration: </span>
                <span className="text-slate-300">
                  {Math.round(
                    (new Date(backup.completed_at).getTime() - new Date(backup.started_at).getTime()) / 1000,
                  )}s
                </span>
              </div>
            )}
          </div>

          {backup.note && (
            <div className="text-sm">
              <span className="text-slate-500">Note: </span>
              <span className="text-slate-300">{backup.note}</span>
            </div>
          )}

          {backup.verified != null && (
            <div
              className={clsx(
                'p-3 rounded-lg border',
                backup.verified ? 'bg-green-500/10 border-green-500/30' : 'bg-red-500/10 border-red-500/30',
              )}
            >
              <div className="flex items-center gap-2 mb-2">
                {backup.verified ? (
                  <ShieldCheck className="w-4 h-4 text-green-400" />
                ) : (
                  <ShieldX className="w-4 h-4 text-red-400" />
                )}
                <span className={clsx('text-sm font-medium', backup.verified ? 'text-green-400' : 'text-red-400')}>
                  {backup.verified ? 'Verified' : 'Verification Failed'}
                </span>
                {backup.verified_at && (
                  <span className="text-xs text-slate-500 ml-auto">{formatDate(backup.verified_at)}</span>
                )}
              </div>
              <div className="grid grid-cols-2 md:grid-cols-3 gap-3 text-sm">
                {backup.checksum && (
                  <div>
                    <p className="text-slate-500 text-xs mb-0.5">Checksum</p>
                    <p className="text-slate-300 font-mono text-xs truncate" title={backup.checksum}>
                      {backup.checksum}
                    </p>
                  </div>
                )}
                {backup.total_files != null && (
                  <div>
                    <p className="text-slate-500 text-xs mb-0.5">Files</p>
                    <p className="text-slate-300 flex items-center gap-1">
                      <FileCheck className="w-3 h-3 text-slate-500" />
                      {backup.total_files.toLocaleString()}
                    </p>
                  </div>
                )}
              </div>
              {backup.verification_json?.tree && Object.keys(backup.verification_json.tree).length > 0 && (
                <div className="mt-2 pt-2 border-t border-slate-700/50">
                  <p className="text-xs text-slate-500 mb-1">Archive Contents</p>
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-x-4 gap-y-0.5">
                    {Object.entries(backup.verification_json.tree)
                      .sort(([, a], [, b]) => b.count - a.count)
                      .map(([name, info]) => (
                        <div key={name} className="flex items-center justify-between text-xs">
                          <span className="text-slate-400 truncate">{name}</span>
                          <span className="text-slate-500 ml-2">{info.count}</span>
                        </div>
                      ))}
                  </div>
                </div>
              )}
              {backup.verification_json?.errors && backup.verification_json.errors.length > 0 && (
                <div className="mt-2 pt-2 border-t border-red-500/20">
                  {backup.verification_json.errors.map((err) => (
                    <p key={err} className="text-xs text-red-400">{err}</p>
                  ))}
                </div>
              )}
            </div>
          )}

          {backup.status === 'failed' && backup.error_message && (
            <div className="p-3 bg-red-500/10 border border-red-500/30 rounded-lg">
              <p className="text-xs text-red-400 font-medium mb-1">Error</p>
              <p className="text-sm text-red-300 whitespace-pre-wrap">{backup.error_message}</p>
            </div>
          )}
        </div>
      </td>
    </tr>
  )
}
