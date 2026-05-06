'use client'

import { useQuery } from '@tanstack/react-query'
import { ExternalLink, Loader2, X } from 'lucide-react'
import Link from 'next/link'
import { fetchMockup, type Mockup } from '@/lib/api/mockups'
import { MockupSurfaceEditor } from './mockup-modal/MockupSurfaceEditor'

interface MockupEditorModalProps {
  projectId: string
  mockupId: string
  open: boolean
  onOpenChange: (open: boolean) => void
  onSaved?: (mockup: Mockup) => void
  onSendToJenny?: (payload: {
    sourceMockup: Mockup
    savedMockup?: Mockup
    content: string
    summary: string
  }) => void
}

export function MockupEditorModal({
  projectId,
  mockupId,
  open,
  onOpenChange,
  onSaved,
  onSendToJenny,
}: MockupEditorModalProps) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['mockup', projectId, mockupId],
    queryFn: () => fetchMockup(projectId, mockupId),
    enabled: open,
  })

  if (!open) return null

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center">
      <div
        className="absolute inset-0 bg-slate-950/92 backdrop-blur-sm"
        onClick={() => onOpenChange(false)}
        role="presentation"
      />
      <div className="relative flex h-[92vh] w-[95vw] max-w-[1800px] flex-col overflow-hidden rounded-xl border border-slate-800 bg-slate-950 shadow-[0_30px_120px_rgba(0,0,0,0.65)]">
        <div className="flex h-11 shrink-0 items-center gap-2 border-b border-slate-800 bg-slate-900/90 px-3">
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-semibold text-slate-100">
              {data?.name ?? 'Design mockup'}
            </div>
            <div className="truncate font-mono text-[10px] text-slate-500">
              {mockupId}
              {data?.version ? ` · v${data.version}` : ''}
              {data?.page_path ? ` · ${data.page_path}` : ''}
            </div>
          </div>
          <Link
            href={`/projects/${projectId}/design`}
            className="inline-flex h-8 items-center gap-1.5 rounded border border-slate-700 bg-slate-950/70 px-2 text-xs text-slate-300 transition-colors hover:border-phosphor-500/50 hover:text-phosphor-200"
          >
            <ExternalLink className="h-3.5 w-3.5" />
            Design
          </Link>
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            className="flex h-8 w-8 items-center justify-center rounded text-slate-400 hover:bg-slate-800 hover:text-slate-100"
            aria-label="Close mockup editor"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="min-h-0 flex-1">
          {isLoading ? (
            <div className="flex h-full items-center justify-center gap-2 text-sm text-slate-500">
              <Loader2 className="h-4 w-4 animate-spin text-phosphor-400" />
              Loading mockup...
            </div>
          ) : error || !data ? (
            <div className="flex h-full items-center justify-center text-sm text-rose-300">
              Failed to load mockup.
            </div>
          ) : (
            <MockupSurfaceEditor
              mockup={data}
              projectId={projectId}
              onSaved={onSaved}
              onSendToJenny={onSendToJenny}
            />
          )}
        </div>
      </div>
    </div>
  )
}
