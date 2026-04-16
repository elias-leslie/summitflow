'use client'

import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Layers3, Sparkles, X } from 'lucide-react'
import { toast } from 'sonner'
import {
  createMockup,
  type CreateMockupRequest,
  type Mockup,
} from '@/lib/api/mockups'
import { getErrorMessage } from '@/lib/utils'

interface CreateMockupDialogProps {
  projectId: string
  open: boolean
  onOpenChange: (open: boolean) => void
  onCreated?: (mockup: Mockup) => void
  parentMockup?: Mockup | null
}

const DEFAULT_TYPE = 'page'

function buildInitialDraft(parentMockup?: Mockup | null): CreateMockupRequest {
  return {
    name: parentMockup ? `${parentMockup.name} iteration` : '',
    description: parentMockup?.description ?? '',
    mockup_type: parentMockup?.mockup_type ?? DEFAULT_TYPE,
    content: '',
    page_path: parentMockup?.page_path ?? '',
    parent_mockup_id: parentMockup?.id,
    generator: 'manual-concept',
    generation_prompt: '',
  }
}

export function CreateMockupDialog({
  projectId,
  open,
  onOpenChange,
  onCreated,
  parentMockup = null,
}: CreateMockupDialogProps): React.ReactElement | null {
  const queryClient = useQueryClient()
  const [draft, setDraft] = useState<CreateMockupRequest>(buildInitialDraft(parentMockup))

  useEffect(() => {
    if (!open) return
    setDraft(buildInitialDraft(parentMockup))
  }, [open, parentMockup])

  const title = parentMockup ? 'Create Mockup Iteration' : 'Create Manual Mockup'
  const helperCopy = parentMockup
    ? `Create a new stored revision linked to ${parentMockup.name}.`
    : 'Store a hand-authored concept, HTML mockup, or design note in the normal mockup workflow.'

  const mutation = useMutation({
    mutationFn: () => createMockup(projectId, draft),
    onSuccess: (mockup) => {
      queryClient.invalidateQueries({ queryKey: ['mockups', projectId] })
      queryClient.invalidateQueries({ queryKey: ['mockup-stats', projectId] })
      toast.success(parentMockup ? 'Mockup iteration created' : 'Mockup created')
      onCreated?.(mockup)
      onOpenChange(false)
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, 'Failed to create mockup'))
    },
  })

  const canSubmit = useMemo(() => {
    return Boolean(draft.name?.trim() && (draft.content?.trim() || draft.description?.trim()))
  }, [draft.content, draft.description, draft.name])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div
        className="absolute inset-0 bg-slate-950/90 backdrop-blur-sm"
        onClick={() => onOpenChange(false)}
        role="presentation"
      />

      <div className="relative mx-4 w-full max-w-3xl rounded-xl bg-slate-900">
        <div className="flex items-center justify-between border-b border-slate-800 p-4">
          <div className="flex items-center gap-3">
            <Sparkles className="h-5 w-5 text-outrun-400" />
            <div>
              <h2 className="text-lg font-semibold text-slate-100 display">
                {title}
              </h2>
              <p className="mt-1 text-sm text-slate-400">
                {helperCopy}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            className="p-2 text-slate-400 transition-colors hover:text-slate-100"
            aria-label="Close dialog"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="grid gap-4 p-6">
          {parentMockup ? (
            <div className="rounded-xl border border-slate-800 bg-slate-950/50 px-4 py-3 text-sm text-slate-300">
              <div className="flex items-center gap-2 text-slate-200">
                <Layers3 className="h-4 w-4 text-cyan-300" />
                Based on v{parentMockup.version} · {parentMockup.name}
              </div>
              {parentMockup.page_path ? (
                <div className="mt-1 text-xs text-slate-500">
                  Page: {parentMockup.page_path}
                </div>
              ) : null}
            </div>
          ) : null}

          <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_12rem]">
            <label className="grid gap-2 text-sm">
              <span className="font-medium text-slate-300">Name</span>
              <input
                value={draft.name ?? ''}
                onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))}
                placeholder="Workspace footer concept"
                className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100"
              />
            </label>

            <label className="grid gap-2 text-sm">
              <span className="font-medium text-slate-300">Type</span>
              <select
                value={draft.mockup_type ?? DEFAULT_TYPE}
                onChange={(event) => setDraft((current) => ({ ...current, mockup_type: event.target.value }))}
                className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100"
              >
                <option value="page">Page</option>
                <option value="layout">Layout</option>
                <option value="component">Component</option>
                <option value="illustration">Illustration</option>
                <option value="icon">Icon</option>
              </select>
            </label>
          </div>

          <label className="grid gap-2 text-sm">
            <span className="font-medium text-slate-300">Description</span>
            <textarea
              value={draft.description ?? ''}
              onChange={(event) => setDraft((current) => ({ ...current, description: event.target.value }))}
              placeholder="Short summary of what changed and why."
              rows={3}
              className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100"
            />
          </label>

          <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
            <label className="grid gap-2 text-sm">
              <span className="font-medium text-slate-300">Target Page</span>
              <input
                value={draft.page_path ?? ''}
                onChange={(event) => setDraft((current) => ({ ...current, page_path: event.target.value }))}
                placeholder="/persona"
                className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100"
              />
            </label>

            <label className="grid gap-2 text-sm">
              <span className="font-medium text-slate-300">Review Notes</span>
              <input
                value={draft.generation_prompt ?? ''}
                onChange={(event) => setDraft((current) => ({ ...current, generation_prompt: event.target.value }))}
                placeholder="Remaining items, rationale, or implementation notes."
                className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100"
              />
            </label>
          </div>

          <label className="grid gap-2 text-sm">
            <span className="font-medium text-slate-300">Mockup Content</span>
            <textarea
              value={draft.content ?? ''}
              onChange={(event) => setDraft((current) => ({ ...current, content: event.target.value }))}
              placeholder="Paste full HTML/CSS for a rendered mockup, or plain text notes if this concept is still schematic."
              rows={16}
              className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 font-mono text-sm text-slate-100"
            />
            <p className="text-xs text-slate-500">
              Full HTML renders in the preview modal. Plain text remains readable as a design note.
            </p>
          </label>
        </div>

        <div className="flex items-center justify-between gap-3 border-t border-slate-800 p-4">
          <div className="text-xs text-slate-500">
            Saved as normal mockup data. No project-specific UI code needed.
          </div>
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => onOpenChange(false)}
              className="btn-secondary"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={() => mutation.mutate()}
              disabled={!canSubmit || mutation.isPending}
              className="btn-primary disabled:opacity-50"
            >
              {mutation.isPending ? 'Saving...' : parentMockup ? 'Create Iteration' : 'Create Mockup'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
