import { Database, HardDrive, ShieldCheck, ShieldX } from 'lucide-react'
import type { Backup } from '@/lib/api/backups'
import { formatBytes, formatDate } from '@/lib/format'

interface PreviewStepProps {
  backup: Backup
}

export function PreviewStep({ backup }: PreviewStepProps) {
  return (
    <div className="space-y-4">
      <div className="p-4 bg-slate-700/50 rounded-lg space-y-3">
        <h3 className="text-sm font-medium text-slate-300 mb-3">
          Backup selected for restore:
        </h3>
        <div className="flex items-center gap-3 text-sm">
          <Database className="w-4 h-4 text-blue-400" />
          <span className="text-slate-300">Database</span>
          <span className="text-slate-500">
            ({formatBytes(backup.db_size_bytes)})
          </span>
        </div>
        <div className="flex items-center gap-3 text-sm">
          <HardDrive className="w-4 h-4 text-purple-400" />
          <span className="text-slate-300">Project Files</span>
          <span className="text-slate-500">
            {backup.files_size_bytes != null
              ? `(${formatBytes(backup.files_size_bytes)})`
              : backup.total_files != null
                ? `(${backup.total_files.toLocaleString()} files)`
                : '(included)'}
          </span>
        </div>
        <div className="flex items-center gap-3 text-sm">
          {backup.verified ? (
            <ShieldCheck className="w-4 h-4 text-green-400" />
          ) : (
            <ShieldX className="w-4 h-4 text-red-400" />
          )}
          <span className="text-slate-300">
            {backup.verified ? 'Verified archive' : 'Archive verification unavailable'}
          </span>
        </div>
      </div>

      <div className="p-4 bg-slate-700/50 rounded-lg">
        <div className="text-sm space-y-2">
          <div className="flex justify-between gap-4">
            <span className="text-slate-400">Archive</span>
            <span className="font-mono text-slate-200 text-right break-all">{backup.name}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-slate-400">Backup ID</span>
            <span className="font-mono text-slate-200">{backup.id}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-slate-400">Created</span>
            <span className="text-slate-200">
              {formatDate(backup.created_at)}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-slate-400">Total Size</span>
            <span className="text-slate-200">
              {formatBytes(backup.size_bytes)}
            </span>
          </div>
          {backup.location && (
            <div className="flex justify-between gap-4">
              <span className="text-slate-400">Restore Source</span>
              <span className="text-slate-200 text-right break-all">{backup.location}</span>
            </div>
          )}
          {backup.note && (
            <div className="flex justify-between">
              <span className="text-slate-400">Note</span>
              <span className="text-slate-200">{backup.note}</span>
            </div>
          )}
        </div>
      </div>

      <div className="p-3 bg-yellow-500/10 border border-yellow-500/30 rounded-lg">
        <p className="text-sm text-yellow-300">
          <strong>Warning:</strong> Restoring will overwrite your current
          database and project files using this exact backup record. This action cannot be undone.
        </p>
      </div>
    </div>
  )
}
