'use client'

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Loader2, Play } from 'lucide-react'
import { runBackupNow } from '@/lib/api/backups'

/** The one action on the page: start the same run the timer starts. */
export function BackUpNow({ running }: { running: boolean }) {
  const queryClient = useQueryClient()
  const run = useMutation({
    mutationFn: () => runBackupNow(true),
    onSettled: () =>
      queryClient.invalidateQueries({ queryKey: ['backup-overview'] }),
  })
  const refused = run.data && !run.data.started
  const busy = run.isPending || running

  return (
    <section
      aria-label="Back up now"
      className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border border-slate-700/60 bg-slate-900/30 px-4 py-3"
    >
      <button
        type="button"
        onClick={() => run.mutate()}
        disabled={busy}
        className="flex items-center gap-1.5 rounded-md border border-phosphor-500/20 bg-phosphor-500/12 px-3 py-1.5 text-xs font-medium text-phosphor-400 transition-all hover:border-phosphor-500/40 hover:bg-phosphor-500/20 focus-visible:outline focus-visible:outline-2 focus-visible:outline-phosphor-400 disabled:opacity-50"
        data-testid="backup-now"
      >
        {busy ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
        ) : (
          <Play className="h-3.5 w-3.5" aria-hidden />
        )}
        {running ? 'Copying to Google Drive' : 'Back up now'}
      </button>
      <p className="min-w-0 text-xs text-slate-500" role="status">
        {run.isError
          ? run.error.message
          : refused
            ? (run.data?.error ?? 'A backup is already running.')
            : run.data?.started
              ? 'Started. The cards update as it goes.'
              : 'Takes a new local point and copies it to Google Drive. Both also run on their own.'}
      </p>
    </section>
  )
}
