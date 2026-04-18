'use client'

import clsx from 'clsx'
import {
  AlertCircle,
  ChevronDown,
  ChevronRight,
  Clock,
  GitBranch,
  Loader2,
  Terminal,
  Zap,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import type { Event } from '@/lib/api/events'
import { getEvents } from '@/lib/api/events'
import { formatDuration } from '@/lib/format'
import { getErrorMessage } from '@/lib/utils'

// ============================================================================
// Types
// ============================================================================

interface SpanNode {
  event: Event
  children: SpanNode[]
  duration: number | null
}

interface SpanTreeProps {
  projectId: string
  traceId: string
  onEventClick?: (event: Event) => void
  className?: string
}

// ============================================================================
// Helpers
// ============================================================================

function buildSpanTree(events: Event[]): SpanNode[] {
  const nodeMap = new Map<string, SpanNode>()
  const roots: SpanNode[] = []

  // Create nodes for all events with span_ids
  for (const event of events) {
    if (!event.span_id) continue
    const existing = nodeMap.get(event.span_id)
    if (existing) {
      // Keep the event with more info (prefer named events)
      if (event.name && !existing.event.name) {
        existing.event = event
      }
      continue
    }
    nodeMap.set(event.span_id, {
      event,
      children: [],
      duration: null,
    })
  }

  // Calculate durations from events with same span_id
  for (const event of events) {
    if (!event.span_id) continue
    const node = nodeMap.get(event.span_id)
    if (!node) continue
    const attrs = event.attributes as Record<string, unknown>
    if (attrs?.duration_ms) {
      node.duration = attrs.duration_ms as number
    }
  }

  // Build parent-child relationships
  for (const node of nodeMap.values()) {
    const parentId = node.event.parent_span_id
    if (parentId) {
      const parent = nodeMap.get(parentId)
      if (parent) {
        parent.children.push(node)
      } else {
        roots.push(node)
      }
    } else {
      roots.push(node)
    }
  }

  // Sort children by timestamp
  const sortChildren = (nodes: SpanNode[]) => {
    nodes.sort(
      (a, b) =>
        new Date(a.event.timestamp).getTime() -
        new Date(b.event.timestamp).getTime(),
    )
    for (const node of nodes) {
      sortChildren(node.children)
    }
  }
  sortChildren(roots)

  return roots
}

const SOURCE_CONFIG: Record<string, { color: string; icon: React.ReactNode }> =
  {
    orchestrator: {
      color: 'text-violet-400',
      icon: <Zap className="h-3.5 w-3.5 text-violet-400" />,
    },
    worker: {
      color: 'text-emerald-400',
      icon: <Terminal className="h-3.5 w-3.5 text-emerald-400" />,
    },
    agent: {
      color: 'text-cyan-400',
      icon: <Terminal className="h-3.5 w-3.5 text-cyan-400" />,
    },
    system: {
      color: 'text-slate-400',
      icon: <GitBranch className="h-3.5 w-3.5 text-slate-400" />,
    },
  }

const LEVEL_BG: Record<string, string> = {
  error: 'bg-red-950/30 border-red-800/40',
  warning: 'bg-amber-950/20 border-amber-800/30',
  info: 'bg-slate-800/30 border-slate-700/40',
  debug: 'bg-slate-800/20 border-slate-700/30',
}

// ============================================================================
// SpanNode Component
// ============================================================================

function SpanNodeRow({
  node,
  depth,
  onEventClick,
}: {
  node: SpanNode
  depth: number
  onEventClick?: (event: Event) => void
}) {
  const [expanded, setExpanded] = useState(depth < 2)
  const hasChildren = node.children.length > 0
  const { event } = node
  const sourceConfig = SOURCE_CONFIG[event.source] || SOURCE_CONFIG.system
  const levelBg = LEVEL_BG[event.level] || LEVEL_BG.info

  const handleClick = useCallback(() => {
    if (hasChildren) {
      setExpanded((prev) => !prev)
    }
    onEventClick?.(event)
  }, [hasChildren, onEventClick, event])

  const label =
    event.name ||
    event.message?.slice(0, 80) ||
    `${event.event_type}:${event.source}`

  return (
    <>
      <div
        role="button"
        tabIndex={0}
        className={clsx(
          'flex items-center gap-2 py-1.5 px-2 rounded-md cursor-pointer hover:bg-slate-700/30 transition-colors border',
          levelBg,
        )}
        style={{ marginLeft: `${depth * 20}px` }}
        onClick={handleClick}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            handleClick()
          }
        }}
        {...(hasChildren && { 'aria-expanded': expanded })}
      >
        {/* Expand/collapse */}
        <span className="w-4 shrink-0">
          {hasChildren ? (
            expanded ? (
              <ChevronDown className="h-3.5 w-3.5 text-slate-500" />
            ) : (
              <ChevronRight className="h-3.5 w-3.5 text-slate-500" />
            )
          ) : (
            <span className="inline-block w-3.5 h-3.5" />
          )}
        </span>

        {/* Source icon */}
        {sourceConfig.icon}

        {/* Event type badge */}
        <span className="text-2xs px-1.5 py-0.5 bg-slate-800/60 rounded text-slate-400 font-mono uppercase shrink-0">
          {event.event_type}
        </span>

        {/* Label */}
        <span className="text-sm text-slate-300 truncate flex-1" title={label}>
          {label}
        </span>

        {/* Duration */}
        {node.duration && (
          <span className="flex items-center gap-1 text-2xs text-slate-500 font-mono tabular-nums shrink-0">
            <Clock className="h-3 w-3" />
            {formatDuration(node.duration)}
          </span>
        )}

        {/* Children count */}
        {hasChildren && (
          <span className="text-2xs px-1.5 py-0.5 bg-slate-800/60 rounded text-slate-500 font-mono shrink-0">
            {node.children.length}
          </span>
        )}

        {/* Error indicator */}
        {event.level === 'error' && (
          <AlertCircle className="h-3.5 w-3.5 text-red-400 shrink-0" />
        )}
      </div>

      {/* Children */}
      {expanded &&
        node.children.map((child) => (
          <SpanNodeRow
            key={child.event.span_id || child.event.id}
            node={child}
            depth={depth + 1}
            onEventClick={onEventClick}
          />
        ))}
    </>
  )
}

// ============================================================================
// SpanTree Component
// ============================================================================

export function SpanTree({
  projectId,
  traceId,
  onEventClick,
  className = '',
}: SpanTreeProps) {
  const [events, setEvents] = useState<Event[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    async function fetchEvents() {
      setIsLoading(true)
      setError(null)
      try {
        const result = await getEvents(projectId, {
          trace_id: traceId,
          limit: 1000,
        })
        if (!cancelled) {
          setEvents(result.events)
        }
      } catch (err) {
        if (!cancelled) {
          setError(getErrorMessage(err, 'Failed to fetch events'))
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false)
        }
      }
    }

    fetchEvents()
    return () => {
      cancelled = true
    }
  }, [projectId, traceId])

  const tree = useMemo(() => buildSpanTree(events), [events])

  if (isLoading) {
    return (
      <div
        className={clsx(
          'flex items-center justify-center py-8 text-slate-600',
          className,
        )}
      >
        <Loader2 className="h-5 w-5 animate-spin mr-2" />
        <span className="text-sm">Loading span tree...</span>
      </div>
    )
  }

  if (error) {
    return (
      <div className={clsx('flex items-center justify-center py-8', className)}>
        <AlertCircle className="h-5 w-5 text-amber-500 mr-2" />
        <span className="text-sm text-amber-500">{error}</span>
      </div>
    )
  }

  if (tree.length === 0) {
    return (
      <div
        className={clsx(
          'flex items-center justify-center py-8 text-slate-600',
          className,
        )}
      >
        <GitBranch className="h-5 w-5 mr-2" />
        <span className="text-sm">No span hierarchy data available</span>
      </div>
    )
  }

  return (
    <div className={clsx('space-y-1 p-2', className)}>
      {tree.map((root) => (
        <SpanNodeRow
          key={root.event.span_id || root.event.id}
          node={root}
          depth={0}
          onEventClick={onEventClick}
        />
      ))}
    </div>
  )
}
