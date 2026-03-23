'use client'

import { clsx } from 'clsx'
import { Loader2, Plus } from 'lucide-react'
import { useState } from 'react'
import { SourceTypeBadge } from '@/components/backup/SourceTypeBadge'
import { type BackupSource, createSourceBackup } from '@/lib/api/backups'

interface CreateBackupModalProps {
  sources: BackupSource[]
  onClose: () => void
  onCreated: () => Promise<void>
}

export function CreateBackupModal({ sources, onClose, onCreated }: CreateBackupModalProps) {
  const [selectedSources, setSelectedSources] = useState<Set<string>>(new Set())
  const [note, setNote] = useState('')
  const [isPending, setIsPending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const toggleSource = (id: string) => {
    setSelectedSources((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const toggleAll = () => {
    if (selectedSources.size === sources.length) {
      setSelectedSources(new Set())
    } else {
      setSelectedSources(new Set(sources.map((s) => s.id)))
    }
  }

  const handleCreate = async () => {
    setIsPending(true)
    setError(null)
    try {
      await Promise.all(
        Array.from(selectedSources).map((sourceId) =>
          createSourceBackup(sourceId, { note: note || undefined }),
        ),
      )
      await onCreated()
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create backups. Please try again.')
    } finally {
      setIsPending(false)
    }
  }

  const count = selectedSources.size

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={onClose}
      data-testid="backup-create-modal"
    >
      <div
        className="bg-slate-800 rounded-lg border border-slate-700 p-6 w-full max-w-md shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-lg font-semibold text-slate-100 display mb-4">Create Manual Backup</h2>

        <div className="space-y-4">
          <div>
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm text-slate-300">Select Sources</span>
              <button
                type="button"
                onClick={toggleAll}
                className="text-xs text-phosphor-400 hover:text-phosphor-300 transition-colors"
              >
                {selectedSources.size === sources.length ? 'Deselect all' : 'Select all'}
              </button>
            </div>
            <div
              className="max-h-56 overflow-y-auto rounded-md border border-slate-600 bg-slate-700 divide-y divide-slate-600/50"
              data-testid="backup-source-select"
            >
              {sources.map((s) => (
                <label
                  key={s.id}
                  className="flex items-center gap-3 px-3 py-2 hover:bg-slate-600/40 cursor-pointer transition-colors"
                >
                  <input
                    type="checkbox"
                    checked={selectedSources.has(s.id)}
                    onChange={() => toggleSource(s.id)}
                    className="rounded border-slate-500 bg-slate-600 text-phosphor-500 focus:ring-phosphor-500 focus:ring-offset-0"
                  />
                  <span className="text-sm text-slate-200 flex items-center gap-2">
                    {s.name}
                    <SourceTypeBadge type={s.source_type} />
                  </span>
                </label>
              ))}
            </div>
          </div>

          <div>
            <label htmlFor="backup-note" className="block text-sm text-slate-300 mb-2">
              Note (optional)
            </label>
            <input
              id="backup-note"
              type="text"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="e.g., Before major refactor"
              className="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded-md
                         text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-phosphor-500"
              data-testid="backup-note-input"
            />
          </div>
        </div>

        <div className="flex items-center justify-end gap-3 mt-6">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 text-sm text-slate-400 hover:text-slate-200 transition-colors"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleCreate}
            disabled={count === 0 || isPending}
            className={clsx(
              'flex items-center gap-2 px-4 py-2 text-sm rounded-md font-medium transition-colors',
              count > 0 && !isPending
                ? 'bg-phosphor-600 text-slate-50 hover:bg-phosphor-500'
                : 'bg-slate-700 text-slate-400 cursor-not-allowed',
            )}
            data-testid="backup-create-confirm"
          >
            {isPending ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                Creating...
              </>
            ) : (
              <>
                <Plus className="w-4 h-4" />
                {count > 1 ? `Create ${count} Backups` : 'Create Backup'}
              </>
            )}
          </button>
        </div>

        {error && <p className="mt-3 text-sm text-rose-400">{error}</p>}
      </div>
    </div>
  )
}
