'use client'

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { RefreshCw, X } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { type Mockup, rerunMockup } from '@/lib/api/mockups'
import { getErrorMessage } from '@/lib/utils'

interface RerunMockupDialogProps {
  mockup: Mockup
  projectId: string
  onClose: () => void
  onCreated: (mockup: Mockup) => void
}

export function RerunMockupDialog({
  mockup,
  projectId,
  onClose,
  onCreated,
}: RerunMockupDialogProps): React.ReactElement {
  const [notes, setNotes] = useState('')
  const queryClient = useQueryClient()
  const mutation = useMutation({
    mutationFn: () => rerunMockup(projectId, mockup.mockup_id, { notes }),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ['mockups', projectId] })
      queryClient.invalidateQueries({ queryKey: ['mockup-stats', projectId] })
      queryClient.invalidateQueries({
        queryKey: ['mockup-history', projectId, mockup.mockup_id],
      })
      toast.success('Mockup revision generated')
      onCreated(result.mockup)
      onClose()
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, 'Failed to rerun mockup'))
    },
  })
  const canSubmit = notes.trim().length > 0 && !mutation.isPending

  return (
    <div className="absolute inset-0 z-20 flex items-center justify-center bg-slate-950/70 backdrop-blur-sm">
      <div className="mx-4 w-full max-w-xl rounded-xl border border-slate-800 bg-slate-900 shadow-2xl">
        <div className="flex items-center justify-between border-b border-slate-800 p-4">
          <div className="flex min-w-0 items-center gap-3">
            <RefreshCw className="h-5 w-5 flex-shrink-0 text-cyan-300" />
            <div className="min-w-0">
              <h2 className="truncate text-lg font-semibold text-slate-100 display">
                Rerun Mockup
              </h2>
              <p className="mt-1 truncate text-sm text-slate-400">
                Based on v{mockup.version}: {mockup.name}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-2 text-slate-400 transition-colors hover:text-slate-100"
            aria-label="Close rerun dialog"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="grid gap-3 p-4">
          <label className="grid gap-2 text-sm">
            <span className="font-medium text-slate-300">Revision Notes</span>
            <textarea
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
              placeholder="Adjust spacing, make the header denser, use the existing project colors, keep the sidebar layout..."
              rows={8}
              className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100"
            />
          </label>
        </div>

        <div className="flex items-center justify-end gap-3 border-t border-slate-800 p-4">
          <button type="button" onClick={onClose} className="btn-secondary">
            Cancel
          </button>
          <button
            type="button"
            onClick={() => mutation.mutate()}
            disabled={!canSubmit}
            className="btn-primary flex items-center gap-2 disabled:opacity-50"
          >
            <RefreshCw
              className={`h-4 w-4 ${mutation.isPending ? 'animate-spin' : ''}`}
            />
            {mutation.isPending ? 'Rerunning...' : 'Rerun'}
          </button>
        </div>
      </div>
    </div>
  )
}
