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

interface FeedbackState {
  tone: 'error' | 'warning'
  message: string
}

const AMBIGUOUS_DISPATCH_PATTERN =
  /(fetch failed|failed to fetch|network|socket hang up|econnreset)/i

function getErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message.trim()) {
    return error.message
  }
  return fallback
}

function pluralize(count: number, singular: string): string {
  return count === 1 ? singular : `${singular}s`
}

function summarizeSourceNames(
  sourceIds: string[],
  sourceNames: Map<string, string>,
): string {
  const names = sourceIds.map(
    (sourceId) => sourceNames.get(sourceId) ?? sourceId,
  )
  if (names.length <= 3) {
    return names.join(', ')
  }
  return `${names.slice(0, 3).join(', ')}, and ${names.length - 3} more`
}

export function CreateBackupModal({
  sources,
  onClose,
  onCreated,
}: CreateBackupModalProps) {
  const [selectedSources, setSelectedSources] = useState<Set<string>>(new Set())
  const [note, setNote] = useState('')
  const [isPending, setIsPending] = useState(false)
  const [feedback, setFeedback] = useState<FeedbackState | null>(null)
  const sourceNames = new Map(sources.map((source) => [source.id, source.name]))

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

  const refreshHistory = async () => {
    try {
      await onCreated()
    } catch {
      // Best-effort refresh. Dispatch status feedback is more important than invalidation failures here.
    }
  }

  const handleCreate = async () => {
    setIsPending(true)
    setFeedback(null)

    const sourceIds = Array.from(selectedSources)
    const fallbackMessage = 'Failed to queue backups. Please try again.'

    try {
      const results = await Promise.allSettled(
        sourceIds.map((sourceId) =>
          createSourceBackup(sourceId, { note: note || undefined }),
        ),
      )
      const queuedIds = sourceIds.filter(
        (_, index) => results[index]?.status === 'fulfilled',
      )
      const failedIds = sourceIds.filter(
        (_, index) => results[index]?.status === 'rejected',
      )
      const failureMessages = results.flatMap((result) =>
        result.status === 'rejected'
          ? [getErrorMessage(result.reason, fallbackMessage)]
          : [],
      )
      const allFailuresAreAmbiguous =
        failureMessages.length > 0 &&
        failureMessages.every((message) =>
          AMBIGUOUS_DISPATCH_PATTERN.test(message),
        )

      if (failedIds.length === 0) {
        await refreshHistory()
        onClose()
        return
      }

      if (queuedIds.length > 0) {
        await refreshHistory()
        setSelectedSources(new Set(failedIds))
        setFeedback({
          tone: 'warning',
          message: `Queued ${queuedIds.length} ${pluralize(queuedIds.length, 'backup')}. ${failedIds.length} ${pluralize(failedIds.length, 'source')} did not confirm: ${summarizeSourceNames(failedIds, sourceNames)}. Check Backup History before retrying.`,
        })
        return
      }

      if (allFailuresAreAmbiguous) {
        await refreshHistory()
        setFeedback({
          tone: 'warning',
          message:
            'Queue confirmation was lost while creating backups. Some backups may still be starting. Check Backup History before retrying.',
        })
        return
      }

      setFeedback({
        tone: 'error',
        message: failureMessages[0] ?? fallbackMessage,
      })
    } catch (err) {
      setFeedback({
        tone: 'error',
        message: getErrorMessage(err, fallbackMessage),
      })
    } finally {
      setIsPending(false)
    }
  }

  const count = selectedSources.size

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/90 backdrop-blur-sm"
      onClick={onClose}
      data-testid="backup-create-modal"
    >
      <div
        className="bg-slate-800 rounded-lg border border-slate-700 p-6 w-full max-w-md shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-lg font-semibold text-slate-100 display mb-4">
          Create Manual Backup
        </h2>

        <div className="space-y-4">
          <div>
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm text-slate-300">Select Sources</span>
              <button
                type="button"
                onClick={toggleAll}
                className="text-xs text-phosphor-400 hover:text-phosphor-300 transition-colors"
              >
                {selectedSources.size === sources.length
                  ? 'Deselect all'
                  : 'Select all'}
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
            <label
              htmlFor="backup-note"
              className="block text-sm text-slate-300 mb-2"
            >
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
                Queueing...
              </>
            ) : (
              <>
                <Plus className="w-4 h-4" />
                {count > 1 ? `Create ${count} Backups` : 'Create Backup'}
              </>
            )}
          </button>
        </div>

        {feedback && (
          <p
            className={clsx(
              'mt-3 text-sm',
              feedback.tone === 'error' ? 'text-rose-400' : 'text-amber-300',
            )}
            role="alert"
          >
            {feedback.message}
          </p>
        )}
      </div>
    </div>
  )
}
