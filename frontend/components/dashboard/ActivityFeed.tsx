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
import { formatDate } from '@/lib/format'
import { POLL_STANDARD, STALE_STANDARD } from '@/lib/polling'
import { getErrorMessage } from '@/lib/utils'

const eventConfig: Record<
  ActivityEventType,
  {
    icon: React.ElementType
    color: {
      text: string
      bg: string
    }
    label: string
  }
> = {
  task: {
    icon: CheckCircle2,
    color: {
      text: 'text-green-400',
      bg: 'bg-green-500/10',
    },
    label: 'Task',
  },
  session: {
    icon: Bot,
    color: {
      text: 'text-purple-400',
      bg: 'bg-purple-500/10',
    },
    label: 'Agent',
  },
  backup: {
    icon: Archive,
    color: {
      text: 'text-blue-400',
      bg: 'bg-blue-500/10',
    },
    label: 'Backup',
  },
  git: {
    icon: GitCommit,
    color: {
      text: 'text-cyan-400',
      bg: 'bg-cyan-500/10',
    },
    label: 'Git',
  },
}

function formatRelativeTime(timestamp: string | null, nowMs: number): string {
  if (!timestamp) return ''
  const date = new Date(timestamp)
  const diffMs = nowMs - date.getTime()
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
  nowMs: number
}

function ActivityRow({
  index,
  style,
  items,
  nowMs,
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
      title={event.timestamp ? formatDate(event.timestamp) : undefined}
    >
      <div
        className={clsx(
          'p-2 rounded-lg flex-shrink-0',
          config.color.bg,
        )}
      >
        {isFailed ? (
          <XCircle className="w-4 h-4 text-red-400" />
        ) : (
          <Icon className={clsx('w-4 h-4', config.color.text)} />
        )}
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm text-slate-300 truncate">{event.message}</p>
        <p className="text-xs text-slate-500 mt-0.5">
          <span className="mr-2 uppercase tracking-wide text-slate-600">
            {config.label}
          </span>
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
        {formatRelativeTime(event.timestamp, nowMs)}
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
  const [now, setNow] = useState(() => Date.now())

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['activity-feed', typeFilter],
    queryFn: () =>
      fetchActivity({
        limit: 100,
        types: typeFilter === 'all' ? undefined : [typeFilter],
      }),
    staleTime: STALE_STANDARD,
    refetchInterval: POLL_STANDARD * 2,
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

  useEffect(() => {
    const intervalId = window.setInterval(() => setNow(Date.now()), 60000)
    return () => window.clearInterval(intervalId)
  }, [])

  const items = data?.items ?? []
  const emptyLabel =
    typeFilter === 'all'
      ? 'No recent activity'
      : `No recent ${TYPE_FILTERS.find((filter) => filter.value === typeFilter)?.label.toLowerCase()} activity`

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
              aria-pressed={typeFilter === f.value}
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
      {isLoading ? (
        <div className="p-8 text-center">
          <Loader2 className="w-8 h-8 text-slate-500 mx-auto animate-spin" />
          <p className="text-sm text-slate-500 mt-3">Loading activity...</p>
        </div>
      ) : error ? (
        <div className="p-8 text-center">
          <XCircle className="w-10 h-10 text-red-400 mx-auto mb-3" />
          <p className="text-sm text-red-400">Failed to load activity</p>
          <p className="mt-1 text-xs text-slate-500">
            {getErrorMessage(error, 'Activity feed is temporarily unavailable')}
          </p>
          <button
            onClick={() => refetch()}
            className="mt-3 text-xs text-slate-400 hover:text-slate-200"
          >
            Try again
          </button>
        </div>
      ) : items.length === 0 ? (
        <div className="p-8 text-center">
          <Activity className="w-10 h-10 text-slate-600 mx-auto mb-3" />
          <p className="text-sm text-slate-500">{emptyLabel}</p>
          <p className="text-xs text-slate-600 mt-1">
            {typeFilter === 'all'
              ? 'Activity will appear here as you use SummitFlow'
              : 'Try another filter to inspect a different activity stream'}
          </p>
        </div>
      ) : (
        <>
          <List
            rowComponent={ActivityRow}
            rowCount={items.length}
            rowHeight={64}
            rowProps={{ items, nowMs: now }}
            style={{ height: listHeight }}
          />
          {data?.has_more && (
            <div className="p-3 text-center border-t border-slate-800">
              <p className="text-xs text-slate-500">
                Showing {items.length} of {data.total} events
              </p>
            </div>
          )}
        </>
      )}
    </div>
  )
}
