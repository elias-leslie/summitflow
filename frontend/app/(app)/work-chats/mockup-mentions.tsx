'use client'

import { Layers3 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { fetchMockupContext, type MockupContext } from '@/lib/api/mockups'
import type { MockupEditorTarget } from './types'

export function extractMockupIds(content: string): string[] {
  const ids = [...(content.match(/\bmk-[a-z0-9]{8,}\b/gi) ?? [])]
  const encodedIds =
    content.match(
      /(?:mockup_id|design_id|artifact_id|artifact)[:="'\s]+(mk-[a-z0-9]{8,})/gi,
    ) ?? []
  encodedIds.forEach((value) => {
    const id = value.match(/\bmk-[a-z0-9]{8,}\b/i)?.[0]
    if (id) ids.push(id)
  })
  return Array.from(new Set(ids))
}

export function MockupMentionCards({
  content,
  projectId,
  paneId,
  onOpenMockup,
}: {
  content: string
  projectId: string | null
  paneId: string
  onOpenMockup: (target: MockupEditorTarget) => void
}) {
  const ids = projectId ? extractMockupIds(content) : []
  const idsKey = ids.join('|')
  const [contexts, setContexts] = useState<Record<string, MockupContext>>({})

  useEffect(() => {
    if (!projectId || !ids.length) return
    let cancelled = false
    Promise.all(
      ids.map((id) =>
        fetchMockupContext(projectId, id)
          .then((context) => [id, context] as const)
          .catch(() => null),
      ),
    ).then((items) => {
      if (cancelled) return
      setContexts(
        Object.fromEntries(
          items.filter(
            (item): item is readonly [string, MockupContext] => item !== null,
          ),
        ),
      )
    })
    return () => {
      cancelled = true
    }
  }, [idsKey, projectId])

  if (!ids.length || !projectId) return null

  return (
    <div className="mt-2 flex flex-wrap gap-2">
      {ids.map((mockupId) => {
        const context = contexts[mockupId]
        return (
          <button
            key={mockupId}
            type="button"
            onClick={() => onOpenMockup({ projectId, mockupId, paneId })}
            title={context?.compact_summary ?? mockupId}
            className="inline-flex max-w-96 items-center gap-1.5 rounded border border-phosphor-500/25 bg-phosphor-500/8 px-2 py-1 text-xs text-phosphor-200 transition-colors hover:border-phosphor-500/50 hover:bg-phosphor-500/12"
          >
            <Layers3 className="h-3.5 w-3.5 shrink-0" />
            <span className="truncate">
              {context
                ? `${context.name} v${context.version}`
                : `Open mock ${mockupId}`}
            </span>
            {context?.annotation_count ? (
              <span className="rounded bg-slate-950/70 px-1 font-mono text-[10px] text-slate-400">
                {context.annotation_count} notes
              </span>
            ) : null}
          </button>
        )
      })}
    </div>
  )
}
