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
      text: 'text-phosphor-400',
      bg: 'bg-phosphor-500/10',
    },
    label: 'Git',
  },
}


function getStatusBadgeClass(status: string): string {
  if (status === 'completed') {
    return 'bg-green-500/20 text-green-400'
  }
  if (status === 'failed') {
    return 'bg-rose-500/20 text-rose-400'
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
      className="px-4 py-1.5"
      data-testid={`activity-item-${event.type}`}
      title={event.timestamp ? formatDate(event.timestamp) : undefined}
    >
      <div className="flex h-full items-center gap-4 rounded-2xl border border-transparent bg-slate-950/20 px-3 py-3 transition-all duration-150 hover:border-slate-700/50 hover:bg-slate-950/72">
        <div className="relative flex h-full w-11 flex-shrink-0 items-center justify-center">
          <span className="absolute inset-y-0 w-px bg-slate-800/70" aria-hidden="true" />
          <div className={clsx('relative z-10 rounded-xl p-2 shadow-[0_12px_26px_-20px_rgba(0,0,0,0.95)]', config.color.bg)}>
            {isFailed ? (
              <XCircle className="h-4 w-4 text-red-400" />
            ) : (
              <Icon className={clsx('h-4 w-4', config.color.text)} />
            )}
          </div>
        </div>
        <div className="min-w-0 flex-1">
          <p className="line-clamp-2 text-sm leading-relaxed text-slate-200">
            {event.message}
          </p>
          <p className="mt-1.5 flex flex-wrap items-center gap-2 text-xs text-slate-500">
            <span className="rounded-full border border-slate-800/70 bg-slate-900/70 px-2 py-0.5 uppercase tracking-[0.16em] text-[10px] text-slate-500">
              {config.label}
            </span>
            <Link
              href={`/projects/${event.project_id}`}
              className="font-mono text-slate-400 hover:text-phosphor-300"
            >
              {event.project_id}
            </Link>
            {event.metadata.status && (
              <span className={clsx('rounded-full px-2 py-0.5 text-[10px] uppercase tracking-[0.14em]', getStatusBadgeClass(event.metadata.status))}>
                {event.metadata.status}
              </span>
            )}
          </p>
        </div>
        <span className="flex-shrink-0 font-mono text-xs text-slate-500">
          {formatTimeAgo(event.timestamp)}
        </span>
      </div>
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
      className={clsx('panel-glass overflow-hidden', className)}
      data-testid="activity-feed"
    >
      <div className="border-b border-slate-800/60 px-4 py-4">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-0.5 rounded-full border border-slate-700/50 bg-slate-900/66 p-1">
            {TYPE_FILTERS.map((filter) => {
              const Icon = filter.icon
              return (
                <button
                  type="button"
                  key={filter.value}
                  onClick={() => setTypeFilter(filter.value)}
                  aria-pressed={typeFilter === filter.value}
                  className={clsx(
                    'flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium transition-all duration-200',
                    typeFilter === filter.value
                      ? 'bg-slate-700/80 text-slate-100 shadow-sm ring-1 ring-white/5'
                      : 'text-slate-500 hover:bg-slate-800/60 hover:text-slate-300',
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
            className="inline-flex items-center gap-1.5 rounded-full border border-slate-700/60 bg-slate-900/66 px-3 py-1.5 text-xs text-slate-300 transition-colors hover:border-slate-600 hover:text-slate-100"
          >
            <RefreshCw className={clsx('h-3 w-3', (isRefetching || isFetchingNextPage) && 'animate-spin')} />
            Refresh
          </button>
        </div>
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500">
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
            className="mt-3 inline-flex items-center gap-1.5 px-3 py-1.5 text-xs text-slate-300 bg-slate-800 border border-slate-700 rounded-md hover:border-slate-600 hover:text-slate-200 transition-colors"
          >
            <RefreshCw className="h-3 w-3" />
            Try again
          </button>
        </div>
      ) : items.length === 0 ? (
        <div className="p-10 text-center">
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
            rowHeight={92}
            rowProps={{ items }}
            style={{ height: listHeight }}
          />
          <div className="border-t border-slate-800/60 p-4 text-center">
            <p className="text-xs text-slate-500">
              Showing {items.length} of {total} events
            </p>
            {hasNextPage && (
              <button
                type="button"
                onClick={() => fetchNextPage()}
                disabled={isFetchingNextPage}
                className="mt-3 inline-flex items-center gap-1.5 rounded-full border border-phosphor-500/18 bg-phosphor-500/10 px-3 py-1.5 text-xs text-phosphor-300 transition-colors hover:bg-phosphor-500/14 disabled:cursor-not-allowed disabled:opacity-50"
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
