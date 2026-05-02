'use client'

import { clsx } from 'clsx'
import {
  Database,
  FileCheck,
  HardDrive,
  ShieldCheck,
  ShieldX,
} from 'lucide-react'
import { SourceTypeBadge } from '@/components/backup/SourceTypeBadge'
import {
  type Backup,
  type BackupSource,
  backupHasDatabase,
} from '@/lib/api/backups'
import { formatBytes, formatDate } from '@/lib/format'

export function BackupExpandedRow({
  backup,
  sourceName,
  sourceType,
  colSpan = 7,
}: {
  backup: Backup
  sourceName: string
  sourceType: BackupSource['source_type'] | undefined
  colSpan?: number
}) {
  const hasDatabase = backupHasDatabase(backup)

  return (
    <tr>
      <td colSpan={colSpan} className="px-0 py-0">
        <div className="mx-4 mb-3 rounded-lg border border-slate-800/60 bg-slate-900/40 p-4 space-y-3">
          {/* Metrics grid */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-1.5">
            <div className="min-w-0 rounded bg-slate-950/50 px-2 py-1.5">
              <div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">
                Source
              </div>
              <div className="truncate text-xs text-slate-200 flex items-center gap-1.5">
                {sourceName}
                {sourceType && <SourceTypeBadge type={sourceType} />}
              </div>
            </div>
            <div className="min-w-0 rounded bg-slate-950/50 px-2 py-1.5">
              <div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">
                Type
              </div>
              <div className="truncate text-xs text-slate-200">
                {backup.backup_type}
              </div>
            </div>
            <div className="min-w-0 rounded bg-slate-950/50 px-2 py-1.5">
              <div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">
                Location
              </div>
              <div className="truncate text-xs text-slate-200 font-mono">
                {backup.location || '-'}
              </div>
            </div>
            <div className="min-w-0 rounded bg-slate-950/50 px-2 py-1.5">
              <div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">
                Name
              </div>
              <div className="truncate text-xs text-slate-200 font-mono">
                {backup.name || '-'}
              </div>
            </div>
          </div>

          {/* Size breakdown */}
          {(hasDatabase ||
            backup.files_size_bytes != null ||
            backup.size_bytes != null) && (
            <div className="flex items-center gap-4 text-xs">
              {hasDatabase && backup.db_size_bytes != null && (
                <div className="flex items-center gap-1.5">
                  <Database className="w-3 h-3 text-blue-400" />
                  <span className="text-slate-500">DB:</span>
                  <span className="text-slate-200 font-mono">
                    {formatBytes(backup.db_size_bytes)}
                  </span>
                </div>
              )}
              {backup.files_size_bytes != null && (
                <div className="flex items-center gap-1.5">
                  <HardDrive className="w-3 h-3 text-purple-400" />
                  <span className="text-slate-500">Files:</span>
                  <span className="text-slate-200 font-mono">
                    {formatBytes(backup.files_size_bytes)}
                  </span>
                </div>
              )}
              {!hasDatabase && (
                <div className="flex items-center gap-1.5">
                  <HardDrive className="w-3 h-3 text-purple-400" />
                  <span className="text-slate-400">Files only</span>
                </div>
              )}
            </div>
          )}

          {/* Timestamps */}
          <div className="flex flex-wrap items-center gap-4 text-xs">
            {backup.started_at && (
              <div>
                <span className="text-slate-500">Started: </span>
                <span className="text-slate-300">
                  {formatDate(backup.started_at)}
                </span>
              </div>
            )}
            {backup.completed_at && (
              <div>
                <span className="text-slate-500">Completed: </span>
                <span className="text-slate-300">
                  {formatDate(backup.completed_at)}
                </span>
              </div>
            )}
            {backup.started_at && backup.completed_at && (
              <div>
                <span className="text-slate-500">Duration: </span>
                <span className="text-slate-300">
                  {Math.round(
                    (new Date(backup.completed_at).getTime() -
                      new Date(backup.started_at).getTime()) /
                      1000,
                  )}
                  s
                </span>
              </div>
            )}
          </div>

          {backup.note && (
            <div className="text-xs">
              <span className="text-slate-500">Note: </span>
              <span className="text-slate-300">{backup.note}</span>
            </div>
          )}

          {/* Verification */}
          {backup.verified != null && (
            <div
              className={clsx(
                'p-3 rounded-lg border',
                backup.verified
                  ? 'bg-emerald-500/8 border-emerald-500/20'
                  : 'bg-red-500/8 border-red-500/20',
              )}
            >
              <div className="flex items-center gap-2 mb-2">
                {backup.verified ? (
                  <ShieldCheck className="w-4 h-4 text-emerald-400" />
                ) : (
                  <ShieldX className="w-4 h-4 text-red-400" />
                )}
                <span
                  className={clsx(
                    'text-xs font-medium',
                    backup.verified ? 'text-emerald-400' : 'text-red-400',
                  )}
                >
                  {backup.verified ? 'Verified' : 'Verification Failed'}
                </span>
                {backup.verified_at && (
                  <span className="text-2xs text-slate-500 ml-auto">
                    {formatDate(backup.verified_at)}
                  </span>
                )}
              </div>
              <div className="grid grid-cols-2 md:grid-cols-3 gap-1.5">
                {backup.checksum && (
                  <div className="min-w-0 rounded bg-slate-950/50 px-2 py-1.5">
                    <div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">
                      Checksum
                    </div>
                    <div
                      className="truncate text-xs text-slate-300 font-mono"
                      title={backup.checksum}
                    >
                      {backup.checksum}
                    </div>
                  </div>
                )}
                {backup.total_files != null && (
                  <div className="min-w-0 rounded bg-slate-950/50 px-2 py-1.5">
                    <div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">
                      Files
                    </div>
                    <div className="text-xs text-slate-300 flex items-center gap-1">
                      <FileCheck className="w-3 h-3 text-slate-500" />
                      {backup.total_files.toLocaleString()}
                    </div>
                  </div>
                )}
              </div>
              {backup.verification_json?.tree &&
                Object.keys(backup.verification_json.tree).length > 0 && (
                  <div className="mt-2 pt-2 border-t border-slate-800/40">
                    <p className="text-[10px] uppercase tracking-[0.14em] text-slate-500 mb-1">
                      Archive Contents
                    </p>
                    <div className="grid grid-cols-2 md:grid-cols-3 gap-x-4 gap-y-0.5">
                      {Object.entries(backup.verification_json.tree)
                        .sort(([, a], [, b]) => b.count - a.count)
                        .map(([name, info]) => (
                          <div
                            key={name}
                            className="flex items-center justify-between text-2xs"
                          >
                            <span className="text-slate-400 truncate">
                              {name}
                            </span>
                            <span className="text-slate-500 ml-2 font-mono">
                              {info.count}
                            </span>
                          </div>
                        ))}
                    </div>
                  </div>
                )}
              {backup.verification_json?.errors &&
                backup.verification_json.errors.length > 0 && (
                  <div className="mt-2 pt-2 border-t border-red-500/15">
                    {backup.verification_json.errors.map((err) => (
                      <p key={err} className="text-xs text-red-400">
                        {err}
                      </p>
                    ))}
                  </div>
                )}
            </div>
          )}

          {/* Error */}
          {backup.status === 'failed' && backup.error_message && (
            <div className="p-3 bg-red-500/8 border border-red-500/20 rounded-lg">
              <p className="text-[10px] uppercase tracking-[0.14em] text-red-400 mb-1">
                Error
              </p>
              <p className="text-xs text-red-300 whitespace-pre-wrap">
                {backup.error_message}
              </p>
            </div>
          )}
        </div>
      </td>
    </tr>
  )
}
