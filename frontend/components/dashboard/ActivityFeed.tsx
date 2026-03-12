'use client'

import { useInfiniteQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import {
  Activity,
  Archive,
  Bot,
  CheckCircle2,
  ChevronDown,
  GitCommit,
  Loader2,
  RefreshCw,
  XCircle,
} from 'lucide-react'
import Link from 'next/link'
import { type ReactElement, useEffect, useRef, useState } from 'react'
import { List, type RowComponentProps } from 'react-window'
import {
  type ActivityEvent,
  type ActivityEventType,
  fetchActivity,
} from '@/lib/api/activity'
import { formatDate, formatTimeAgo } from '@/lib/format'
import { POLL_SLOW, POLL_STANDARD, STALE_STANDARD } from '@/lib/polling'
import { getErrorMessage } from '@/lib/utils'

const PAGE_SIZE = 50

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


function getStatusBadgeClass(status: string): string {
  if (status === 'completed') {
    return 'bg-green-500/20 text-green-400'
  }
  if (status === 'failed') {
    return 'bg-red-500/20 text-red-400'
  }
  if (status === 'blocked') {
    return 'bg-amber-500/20 text-amber-300'
  }
  if (status === 'cancelled') {
    return 'bg-slate-600 text-slate-300'
  }
  return 'bg-slate-600 text-slate-400'
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
      className="flex items-center gap-3 border-b border-slate-800/50 px-4 hover:bg-slate-800/30 transition-colors"
      data-testid={`activity-item-${event.type}`}
      title={event.timestamp ? formatDate(event.timestamp) : undefined}
    >
      <div className={clsx('flex-shrink-0 rounded-lg p-2', config.color.bg)}>
        {isFailed ? (
          <XCircle className="h-4 w-4 text-red-400" />
        ) : (
          <Icon className={clsx('h-4 w-4', config.color.text)} />
        )}
      </div>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm text-slate-300">{event.message}</p>
        <p className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-slate-500">
          <span className="uppercase tracking-wide text-slate-600">{config.label}</span>
          <Link
            href={`/projects/${event.project_id}`}
            className="font-mono text-slate-400 hover:text-phosphor-300"
          >
            {event.project_id}
          </Link>
          {event.metadata.status && (
            <span className={clsx('rounded px-1.5 py-0.5 text-xs', getStatusBadgeClass(event.metadata.status))}>
              {event.metadata.status}
            </span>
          )}
        </p>
      </div>
      <span className="flex-shrink-0 font-mono text-xs text-slate-500">
        {formatTimeAgo(event.timestamp)}
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
  // Tick counter to force re-renders so relative timestamps update
  const [, setTick] = useState(0)

  const {
    data,
    isLoading,
    error,
    refetch,
    isRefetching,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
    dataUpdatedAt,
  } = useInfiniteQuery({
    queryKey: ['activity-feed', typeFilter],
    queryFn: ({ pageParam }) =>
      fetchActivity({
        limit: PAGE_SIZE,
        offset: pageParam,
        types: typeFilter === 'all' ? undefined : [typeFilter],
      }),
    initialPageParam: 0,
    getNextPageParam: (lastPage) =>
      lastPage.has_more ? lastPage.offset + lastPage.items.length : undefined,
    staleTime: STALE_STANDARD,
    refetchInterval: POLL_STANDARD * 2,
  })

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
    const intervalId = window.setInterval(() => setTick((t) => t + 1), POLL_SLOW)
    return () => window.clearInterval(intervalId)
  }, [])

  const pages = data?.pages ?? []
  const items = pages.flatMap((page) => page.items)
  const total = pages[0]?.total ?? items.length
  const lastUpdated =
    dataUpdatedAt > 0 ? formatTimeAgo(new Date(dataUpdatedAt).toISOString(), 'never') : 'never'
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
      <div className="border-b border-slate-800 px-3 py-2">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-1">
            {TYPE_FILTERS.map((filter) => {
              const Icon = filter.icon
              return (
                <button
                  type="button"
                  key={filter.value}
                  onClick={() => setTypeFilter(filter.value)}
                  aria-pressed={typeFilter === filter.value}
                  className={clsx(
                    'flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs transition-colors',
                    typeFilter === filter.value
                      ? 'bg-slate-700 text-white'
                      : 'text-slate-500 hover:bg-slate-800/50 hover:text-slate-300',
                  )}
                >
                  <Icon className="h-3 w-3" />
                  {filter.label}
                </button>
              )
            })}
          </div>
          <button
            type="button"
            onClick={() => refetch()}
            className="inline-flex items-center gap-1 text-[11px] text-slate-500 transition-colors hover:text-slate-300"
          >
            <RefreshCw className={clsx('h-3 w-3', (isRefetching || isFetchingNextPage) && 'animate-spin')} />
            Refresh
          </button>
        </div>
        <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-[11px] text-slate-500">
          <span>
            {isLoading
              ? 'Loading latest activity'
              : `${total} item${total === 1 ? '' : 's'}${typeFilter === 'all' ? '' : ` in ${TYPE_FILTERS.find((filter) => filter.value === typeFilter)?.label.toLowerCase()}`}`}
          </span>
          <span>Updated {lastUpdated}</span>
        </div>
      </div>
      {isLoading ? (
        <div className="p-8 text-center">
          <Loader2 className="mx-auto h-8 w-8 animate-spin text-slate-500" />
          <p className="mt-3 text-sm text-slate-500">Loading activity...</p>
        </div>
      ) : error ? (
        <div className="p-8 text-center">
          <XCircle className="mx-auto mb-3 h-10 w-10 text-red-400" />
          <p className="text-sm text-red-400">Failed to load activity</p>
          <p className="mt-1 text-xs text-slate-500">
            {getErrorMessage(error, 'Activity feed is temporarily unavailable')}
          </p>
          <button
            type="button"
            onClick={() => refetch()}
            className="mt-3 text-xs text-slate-400 hover:text-slate-200"
          >
            Try again
          </button>
        </div>
      ) : items.length === 0 ? (
        <div className="p-8 text-center">
          <Activity className="mx-auto mb-3 h-10 w-10 text-slate-600" />
          <p className="text-sm text-slate-500">{emptyLabel}</p>
          <p className="mt-1 text-xs text-slate-600">
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
            rowProps={{ items }}
            style={{ height: listHeight }}
          />
          <div className="border-t border-slate-800 p-3 text-center">
            <p className="text-xs text-slate-500">
              Showing {items.length} of {total} events
            </p>
            {hasNextPage && (
              <button
                type="button"
                onClick={() => fetchNextPage()}
                disabled={isFetchingNextPage}
                className="mt-2 inline-flex items-center gap-1 text-xs text-phosphor-400 transition-colors hover:text-phosphor-300 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {isFetchingNextPage ? (
                  <>
                    <Loader2 className="h-3 w-3 animate-spin" />
                    Loading older activity...
                  </>
                ) : (
                  <>
                    <ChevronDown className="h-3 w-3" />
                    Load older activity
                  </>
                )}
              </button>
            )}
          </div>
        </>
      )}
    </div>
  )
}
