'use client'

import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import {
  Activity,
  Archive,
  Bot,
  CheckCircle2,
  GitCommit,
  Loader2,
  XCircle,
} from 'lucide-react'
import { type ReactElement, useEffect, useRef, useState } from 'react'
import { List, type RowComponentProps } from 'react-window'
import {
  type ActivityEvent,
  type ActivityEventType,
  fetchActivity,
} from '@/lib/api/activity'

const eventConfig: Record<
  ActivityEventType,
  { icon: React.ElementType; color: string; label: string }
> = {
  task: {
    icon: CheckCircle2,
    color: 'text-green-400 bg-green-500/10',
    label: 'Task',
  },
  session: {
    icon: Bot,
    color: 'text-purple-400 bg-purple-500/10',
    label: 'Agent',
  },
  backup: {
    icon: Archive,
    color: 'text-blue-400 bg-blue-500/10',
    label: 'Backup',
  },
  git: {
    icon: GitCommit,
    color: 'text-cyan-400 bg-cyan-500/10',
    label: 'Git',
  },
}

function formatRelativeTime(timestamp: string | null): string {
  if (!timestamp) return ''
  const date = new Date(timestamp)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffSec = Math.floor(diffMs / 1000)
  const diffMin = Math.floor(diffSec / 60)
  const diffHr = Math.floor(diffMin / 60)
  const diffDays = Math.floor(diffHr / 24)

  if (diffSec < 60) return 'Just now'
  if (diffMin < 60) return `${diffMin}m ago`
  if (diffHr < 24) return `${diffHr}h ago`
  if (diffDays < 7) return `${diffDays}d ago`
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

interface ActivityRowProps {
  items: ActivityEvent[]
}

function ActivityRow({
  index,
  style,
  items,
}: RowComponentProps<ActivityRowProps>): ReactElement | null {
  const event = items[index]
  if (!event) return null

  const config = eventConfig[event.type]
  const Icon = config.icon
  const isFailed = event.metadata.status === 'failed'

  return (
    <div
      style={style}
      className="px-4 flex items-center gap-3 hover:bg-slate-800/30 transition-colors border-b border-slate-800/50"
      data-testid={`activity-item-${event.type}`}
    >
      <div
        className={clsx(
          'p-2 rounded-lg flex-shrink-0',
          config.color.split(' ')[1],
        )}
      >
        {isFailed ? (
          <XCircle className="w-4 h-4 text-red-400" />
        ) : (
          <Icon className={clsx('w-4 h-4', config.color.split(' ')[0])} />
        )}
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm text-slate-300 truncate">{event.message}</p>
        <p className="text-xs text-slate-500 mt-0.5">
          <span className="font-mono">{event.project_id}</span>
          {event.metadata.status && (
            <span
              className={clsx(
                'ml-2 px-1.5 py-0.5 rounded text-xs',
                event.metadata.status === 'completed'
                  ? 'bg-green-500/20 text-green-400'
                  : event.metadata.status === 'failed'
                    ? 'bg-red-500/20 text-red-400'
                    : 'bg-slate-600 text-slate-400',
              )}
            >
              {event.metadata.status}
            </span>
          )}
        </p>
      </div>
      <span className="text-xs text-slate-500 font-mono flex-shrink-0">
        {formatRelativeTime(event.timestamp)}
      </span>
    </div>
  )
}

const TYPE_FILTERS: {
  value: ActivityEventType | 'all'
  label: string
  icon: React.ElementType
}[] = [
  { value: 'all', label: 'All', icon: Activity },
  { value: 'session', label: 'Agents', icon: Bot },
  { value: 'task', label: 'Tasks', icon: CheckCircle2 },
  { value: 'git', label: 'Git', icon: GitCommit },
  { value: 'backup', label: 'Backups', icon: Archive },
]

interface ActivityFeedProps {
  className?: string
  defaultFilter?: ActivityEventType | 'all'
}

export function ActivityFeed({ className, defaultFilter = 'all' }: ActivityFeedProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [listHeight, setListHeight] = useState(400)
  const [typeFilter, setTypeFilter] = useState<ActivityEventType | 'all'>(defaultFilter)

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['activity-feed', typeFilter],
    queryFn: () =>
      fetchActivity({
        limit: 100,
        types: typeFilter === 'all' ? undefined : [typeFilter],
      }),
    refetchInterval: 30000,
  })

  // Calculate height to fill available space
  useEffect(() => {
    const updateHeight = () => {
      if (containerRef.current) {
        const rect = containerRef.current.getBoundingClientRect()
        const availableHeight = window.innerHeight - rect.top - 32
        setListHeight(Math.max(200, Math.min(availableHeight, 600)))
      }
    }

    updateHeight()
    window.addEventListener('resize', updateHeight)
    return () => window.removeEventListener('resize', updateHeight)
  }, [])

  if (isLoading) {
    return (
      <div className={clsx('card p-8 text-center', className)}>
        <Loader2 className="w-8 h-8 text-slate-500 mx-auto animate-spin" />
        <p className="text-sm text-slate-500 mt-3">Loading activity...</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className={clsx('card p-8 text-center', className)}>
        <XCircle className="w-10 h-10 text-red-400 mx-auto mb-3" />
        <p className="text-sm text-red-400">Failed to load activity</p>
        <button
          onClick={() => refetch()}
          className="mt-3 text-xs text-slate-400 hover:text-slate-200"
        >
          Try again
        </button>
      </div>
    )
  }

  const items = data?.items ?? []

  if (items.length === 0) {
    return (
      <div className={clsx('card p-8 text-center', className)}>
        <Activity className="w-10 h-10 text-slate-600 mx-auto mb-3" />
        <p className="text-sm text-slate-500">No recent activity</p>
        <p className="text-xs text-slate-600 mt-1">
          Activity will appear here as you use SummitFlow
        </p>
      </div>
    )
  }

  return (
    <div
      ref={containerRef}
      className={clsx('card overflow-hidden', className)}
      data-testid="activity-feed"
    >
      <div className="flex items-center gap-1 px-3 py-2 border-b border-slate-800">
        {TYPE_FILTERS.map((f) => {
          const Icon = f.icon
          return (
            <button
              key={f.value}
              onClick={() => setTypeFilter(f.value)}
              className={clsx(
                'flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs transition-colors',
                typeFilter === f.value
                  ? 'bg-slate-700 text-white'
                  : 'text-slate-500 hover:text-slate-300 hover:bg-slate-800/50',
              )}
            >
              <Icon className="w-3 h-3" />
              {f.label}
            </button>
          )
        })}
      </div>
      <List
        rowComponent={ActivityRow}
        rowCount={items.length}
        rowHeight={64}
        rowProps={{ items }}
        style={{ height: listHeight }}
      />
      {data?.has_more && (
        <div className="p-3 text-center border-t border-slate-800">
          <p className="text-xs text-slate-500">
            Showing {items.length} of {data.total} events
          </p>
        </div>
      )}
    </div>
  )
}
