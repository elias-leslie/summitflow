'use client'

import clsx from 'clsx'
import {
  AlertTriangle,
  Code2,
  Eye,
  FileEdit,
  FlaskConical,
  Gauge,
  GitBranch,
  Loader2,
  Play,
} from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { fetchNarrationTimeline } from '@/lib/api/tasks-observability'
import type { NarrationTag, NarrationTagType } from '@/lib/api/tasks'

interface NarrationTimelineProps {
  taskId: string
  pollInterval?: number
  isLive?: boolean
}

const TAG_CONFIG: Record<
  NarrationTagType,
  { icon: typeof Play; label: string; color: string }
> = {
  started: { icon: Play, label: 'Started', color: 'text-blue-400' },
  found: { icon: Eye, label: 'Found', color: 'text-cyan-400' },
  modified: { icon: FileEdit, label: 'Modified', color: 'text-amber-400' },
  tested: { icon: FlaskConical, label: 'Tested', color: 'text-emerald-400' },
  confidence: { icon: Gauge, label: 'Confidence', color: 'text-purple-400' },
  blocked: { icon: AlertTriangle, label: 'Blocked', color: 'text-rose-400' },
  decision: { icon: GitBranch, label: 'Decision', color: 'text-indigo-400' },
}

function TagIcon({ tagType }: { tagType: NarrationTagType }) {
  const config = TAG_CONFIG[tagType] ?? {
    icon: Code2,
    label: tagType,
    color: 'text-slate-400',
  }
  const Icon = config.icon
  return <Icon className={clsx('w-3.5 h-3.5 flex-shrink-0', config.color)} />
}

function ConfidenceBadge({ content }: { content: string }) {
  const match = content.match(/^(\d+)/)
  if (!match) return null
  const score = parseInt(match[1], 10)
  const color =
    score >= 80
      ? 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20'
      : score >= 50
        ? 'text-amber-400 bg-amber-500/10 border-amber-500/20'
        : 'text-rose-400 bg-rose-500/10 border-rose-500/20'
  return (
    <span
      className={clsx('inline-flex items-center px-1.5 py-0.5 text-2xs font-mono rounded border', color)}
    >
      {score}%
    </span>
  )
}

function NarrationEntry({ tag }: { tag: NarrationTag }) {
  const config = TAG_CONFIG[tag.tag_type]
  const isConfidence = tag.tag_type === 'confidence'

  return (
    <div className="flex items-start gap-2.5 py-1.5 group">
      <div className="mt-0.5">
        <TagIcon tagType={tag.tag_type} />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-2xs font-medium text-slate-500 uppercase tracking-wider">
            {config?.label ?? tag.tag_type}
          </span>
          {isConfidence && <ConfidenceBadge content={tag.content} />}
          <span className="text-2xs text-slate-600 ml-auto opacity-0 group-hover:opacity-100 transition-opacity">
            {new Date(tag.created_at).toLocaleTimeString()}
          </span>
        </div>
        <p className="text-sm text-slate-300 mt-0.5 leading-relaxed">
          {isConfidence
            ? tag.content.replace(/^\d+\s*[-—]\s*/, '')
            : tag.content}
        </p>
      </div>
    </div>
  )
}

export function NarrationTimeline({
  taskId,
  pollInterval = 0,
  isLive = false,
}: NarrationTimelineProps) {
  const [tags, setTags] = useState<NarrationTag[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchTags = useCallback(async () => {
    try {
      const data = await fetchNarrationTimeline(taskId)
      setTags(data.tags)
      setError(null)
    } catch {
      setError('Failed to load progress')
    } finally {
      setIsLoading(false)
    }
  }, [taskId])

  useEffect(() => {
    fetchTags()
    if (!isLive || !pollInterval) return
    const interval = setInterval(fetchTags, pollInterval)
    return () => clearInterval(interval)
  }, [fetchTags, isLive, pollInterval])

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 py-3 text-slate-500">
        <Loader2 className="w-4 h-4 animate-spin" />
        <span className="text-xs">Loading progress...</span>
      </div>
    )
  }

  if (error) {
    return (
      <p className="text-xs text-slate-600 italic py-2">{error}</p>
    )
  }

  if (tags.length === 0) {
    return (
      <p className="text-xs text-slate-600 italic py-2">
        No progress narration recorded
      </p>
    )
  }

  const lastConfidence = [...tags]
    .reverse()
    .find((t) => t.tag_type === 'confidence')

  return (
    <div className="space-y-0.5">
      {lastConfidence && (
        <div className="flex items-center gap-2 mb-3 px-3 py-2 rounded-lg bg-slate-800/50 border border-slate-700/50">
          <Gauge className="w-4 h-4 text-purple-400" />
          <span className="text-xs text-slate-400">Agent confidence:</span>
          <ConfidenceBadge content={lastConfidence.content} />
          <span className="text-xs text-slate-500 truncate">
            {lastConfidence.content.replace(/^\d+\s*[-—]\s*/, '')}
          </span>
        </div>
      )}
      <div className="divide-y divide-slate-800/50">
        {tags.map((tag) => (
          <NarrationEntry key={tag.id} tag={tag} />
        ))}
      </div>
    </div>
  )
}
