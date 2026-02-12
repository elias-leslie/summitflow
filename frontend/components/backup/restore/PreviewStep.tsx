import { Database, HardDrive } from 'lucide-react'
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
          What will be restored:
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
            ({formatBytes(backup.files_size_bytes)})
          </span>
        </div>
      </div>

      <div className="p-4 bg-slate-700/50 rounded-lg">
        <div className="text-sm space-y-2">
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
          database and project files. This action cannot be undone.
        </p>
      </div>
    </div>
  )
}
