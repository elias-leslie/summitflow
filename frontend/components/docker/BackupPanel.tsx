'use client'

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { dockerApi } from '@/lib/api/docker'

export function BackupPanel() {
  const [note, setNote] = useState('')
  const queryClient = useQueryClient()

  const { data: backups, isLoading } = useQuery({
    queryKey: ['docker', 'backups'],
    queryFn: dockerApi.getBackups,
  })

  const backupMut = useMutation({
    mutationFn: () => dockerApi.backup(note),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['docker', 'backups'] })
      setNote('')
    },
  })

  const restoreMut = useMutation({
    mutationFn: (filename: string) => dockerApi.restore(filename),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['docker', 'backups'] })
    },
  })

  return (
    <div className="rounded-lg border border-neutral-700 bg-neutral-800/30 p-4">
      <h2 className="text-sm font-medium text-white mb-4">Backups</h2>

      {/* Create backup */}
      <div className="flex gap-2 mb-4">
        <input
          type="text"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="Backup note (optional)"
          className="flex-1 text-xs px-3 py-1.5 rounded bg-neutral-800 border border-neutral-700 text-neutral-300 placeholder:text-neutral-600 focus:outline-none focus:border-neutral-500"
        />
        <button
          onClick={() => backupMut.mutate()}
          disabled={backupMut.isPending}
          className="text-xs px-3 py-1.5 rounded bg-blue-500/10 text-blue-400 hover:bg-blue-500/20 disabled:opacity-50 transition-colors whitespace-nowrap"
        >
          {backupMut.isPending ? 'Creating...' : 'Create Backup'}
        </button>
      </div>

      {backupMut.isSuccess && (
        <p className="text-xs text-emerald-400 mb-3">
          {backupMut.data.message}
        </p>
      )}

      {restoreMut.isSuccess && (
        <p className="text-xs text-amber-400 mb-3">
          {restoreMut.data.message}
        </p>
      )}

      {/* Backup list */}
      {isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="h-6 bg-neutral-800 rounded animate-pulse" />
          ))}
        </div>
      ) : !backups?.length ? (
        <p className="text-sm text-neutral-500">No backups yet</p>
      ) : (
        <div className="space-y-1 max-h-60 overflow-y-auto">
          {backups.map((b) => (
            <div
              key={b.filename}
              className="flex items-center justify-between text-xs py-1.5 px-2 rounded hover:bg-neutral-800/50"
            >
              <div>
                <span className="text-neutral-300">{b.filename}</span>
                <span className="text-neutral-600 ml-2">
                  {b.size_mb} MB
                </span>
              </div>
              <button
                onClick={() => {
                  if (
                    confirm(
                      `Restore from ${b.filename}? This will overwrite all databases.`
                    )
                  ) {
                    restoreMut.mutate(b.filename)
                  }
                }}
                disabled={restoreMut.isPending}
                className="text-xs px-2 py-0.5 rounded bg-amber-500/10 text-amber-400 hover:bg-amber-500/20 disabled:opacity-50 transition-colors"
              >
                Restore
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
