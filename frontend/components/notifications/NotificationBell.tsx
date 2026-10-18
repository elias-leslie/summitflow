'use client'

import { clsx } from 'clsx'
import {
  AlertCircle,
  AlertTriangle,
  Bell,
  CheckCircle,
  Info,
  X,
} from 'lucide-react'
import Link from 'next/link'
import { useCallback, useEffect, useState } from 'react'
import { toast } from 'sonner'
import {
  dismissAllNotifications,
  dismissNotification,
  fetchNotificationCount,
  fetchNotifications,
  markNotificationRead,
  type Notification,
} from '@/lib/api'
import { POLL_NOTIFICATIONS } from '@/lib/polling'
import { notificationHref } from './notificationLink'
import {
  dismissAllGlobalNotifications,
  fetchGlobalNotificationCount,
  fetchGlobalNotifications,
} from './notificationScope'

interface NotificationBellProps {
  /** Project scope; null shows notifications across all projects. */
  projectId: string | null
  className?: string
}

const severityIcons = {
  info: Info,
  warning: AlertTriangle,
  error: AlertCircle,
  critical: AlertCircle,
}

const PAGE_SIZE = 10

const severityColors = {
  info: 'text-blue-400',
  warning: 'text-amber-400',
  error: 'text-rose-400',
  critical: 'text-rose-500',
}

export function NotificationBell({
  projectId,
  className,
}: NotificationBellProps) {
  const [isOpen, setIsOpen] = useState(false)
  const [pendingCount, setPendingCount] = useState(0)
  const [countError, setCountError] = useState(false)
  const [notifications, setNotifications] = useState<Notification[]>([])
  const [total, setTotal] = useState(0)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [loadingMore, setLoadingMore] = useState(false)
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)

  // Fetch pending count periodically
  useEffect(() => {
    const fetchCount = async () => {
      try {
        const count = projectId
          ? await fetchNotificationCount(projectId)
          : await fetchGlobalNotificationCount()
        setPendingCount(count)
        setCountError(false)
      } catch {
        // Never show a stale or zero count as if it were real.
        setPendingCount(0)
        setCountError(true)
      }
    }

    fetchCount()
    const interval = setInterval(fetchCount, POLL_NOTIFICATIONS)
    return () => clearInterval(interval)
  }, [projectId])

  // Fetch notifications when dropdown opens
  const loadNotifications = useCallback(async () => {
    setLoading(true)
    setLoadError(null)
    try {
      const data = projectId
        ? await fetchNotifications(projectId, { limit: PAGE_SIZE })
        : await fetchGlobalNotifications({ limit: PAGE_SIZE })
      setNotifications(data.items)
      setTotal(data.total)
      setPendingCount(data.pending_count)
      setCountError(false)
    } catch {
      setLoadError('Failed to load notifications')
    } finally {
      setLoading(false)
    }
  }, [projectId])

  const loadMore = async () => {
    setLoadingMore(true)
    try {
      const page = { limit: PAGE_SIZE, offset: notifications.length }
      const data = projectId
        ? await fetchNotifications(projectId, page)
        : await fetchGlobalNotifications(page)
      setNotifications((prev) => {
        const seen = new Set(prev.map((n) => n.id))
        return [...prev, ...data.items.filter((n) => !seen.has(n.id))]
      })
      setTotal(data.total)
      setPendingCount(data.pending_count)
    } catch {
      toast.error('Failed to load more notifications')
    } finally {
      setLoadingMore(false)
    }
  }

  const handleToggle = () => {
    if (!isOpen) {
      loadNotifications()
    }
    setIsOpen(!isOpen)
  }

  const handleNotificationClick = async (notification: Notification) => {
    setExpandedId((current) =>
      current === notification.id ? null : notification.id,
    )
    if (notification.status === 'pending') {
      try {
        await markNotificationRead(notification.project_id, notification.id)
        setNotifications((prev) =>
          prev.map((n) =>
            n.id === notification.id ? { ...n, status: 'read' as const } : n,
          ),
        )
        setPendingCount((prev) => Math.max(0, prev - 1))
      } catch {
        toast.error('Failed to mark notification as read')
      }
    }
  }

  const handleDismiss = async (
    e: React.MouseEvent,
    notification: Notification,
  ) => {
    e.stopPropagation()
    try {
      await dismissNotification(notification.project_id, notification.id)
      setNotifications((prev) => prev.filter((n) => n.id !== notification.id))
      setTotal((prev) => Math.max(0, prev - 1))
      if (notification.status === 'pending') {
        setPendingCount((prev) => Math.max(0, prev - 1))
      }
    } catch {
      toast.error('Failed to dismiss notification')
    }
  }

  return (
    <div className={clsx('relative', className)}>
      {/* Bell Button */}
      <button
        type="button"
        onClick={handleToggle}
        className="btn-ghost p-2 rounded-lg relative"
        aria-label={
          countError ? 'Notifications (count unavailable)' : 'Notifications'
        }
        aria-expanded={isOpen}
        aria-haspopup="dialog"
        title="Notifications"
      >
        <Bell className="w-4 h-4" />
        {countError ? (
          <span
            data-testid="notification-count-error"
            title="Notification count unavailable"
            className="absolute -top-0.5 -right-0.5 h-[10px] w-[10px] rounded-full border border-amber-400 bg-slate-900"
          />
        ) : null}
        {!countError && pendingCount > 0 && (
          <span className="absolute -top-0.5 -right-0.5 min-w-[18px] h-[18px] px-1 flex items-center justify-center text-2xs font-medium bg-rose-500 text-slate-50 rounded-full">
            {pendingCount > 99 ? '99+' : pendingCount}
          </span>
        )}
      </button>

      {/* Dropdown */}
      {isOpen && (
        <>
          {/* Backdrop */}
          <div
            className="fixed inset-0 z-40"
            role="presentation"
            onClick={() => setIsOpen(false)}
          />

          {/* Dropdown Content */}
          <div className="absolute right-0 top-full mt-2 w-80 sm:w-96 bg-slate-900/95 backdrop-blur-sm border border-slate-700/80 rounded-xl shadow-xl shadow-black/40 z-50 overflow-hidden">
            {/* Header */}
            <div className="flex items-center justify-between px-4 py-3 border-b border-slate-700">
              <h3 className="text-sm font-medium text-slate-200">
                Notifications
              </h3>
              {pendingCount > 0 && (
                <div className="flex items-center gap-2">
                  <span className="text-xs text-slate-400">
                    {pendingCount} pending
                  </span>
                  <button
                    type="button"
                    onClick={async () => {
                      try {
                        if (projectId) {
                          await dismissAllNotifications(projectId)
                        } else {
                          await dismissAllGlobalNotifications()
                        }
                        setNotifications([])
                        setTotal(0)
                        setPendingCount(0)
                        toast.success('All notifications dismissed')
                      } catch {
                        toast.error('Failed to dismiss notifications')
                      }
                    }}
                    className="text-xs text-slate-500 hover:text-slate-300 transition-colors"
                  >
                    Dismiss all
                  </button>
                </div>
              )}
            </div>

            {/* Notification List */}
            <div className="max-h-[min(400px,70vh)] overflow-y-auto">
              {loading ? (
                <div className="p-4 text-center text-slate-500 text-sm">
                  Loading...
                </div>
              ) : loadError ? (
                <div className="p-6 text-center">
                  <AlertCircle className="w-8 h-8 text-rose-500 mx-auto mb-2" />
                  <p className="text-slate-300 text-sm">{loadError}</p>
                  <button
                    type="button"
                    onClick={() => void loadNotifications()}
                    className="mt-3 text-xs text-phosphor-400 hover:text-phosphor-300"
                  >
                    Try again
                  </button>
                </div>
              ) : notifications.length === 0 ? (
                <div className="p-8 text-center">
                  <CheckCircle className="w-8 h-8 text-slate-600 mx-auto mb-2" />
                  <p className="text-slate-500 text-sm">All caught up!</p>
                  <p className="text-slate-600 text-xs mt-1">
                    No pending notifications
                  </p>
                </div>
              ) : (
                <>
                  {notifications.map((notification) => {
                    const Icon = severityIcons[notification.severity]
                    const expanded = expandedId === notification.id
                    const href = expanded
                      ? notificationHref(notification)
                      : null
                    return (
                      <div
                        key={notification.id}
                        className={clsx(
                          'group relative border-b border-slate-800 hover:bg-slate-800/50 transition-colors',
                          notification.status === 'pending' &&
                            'bg-slate-800/30',
                        )}
                      >
                        <button
                          type="button"
                          aria-expanded={expanded}
                          onClick={() => handleNotificationClick(notification)}
                          className="flex w-full items-start gap-3 py-3 pl-4 pr-10 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-phosphor-500"
                        >
                          <Icon
                            className={clsx(
                              'w-5 h-5 mt-0.5 flex-shrink-0',
                              severityColors[notification.severity],
                            )}
                          />
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2">
                              <span
                                className={clsx(
                                  'text-sm font-medium',
                                  expanded ? 'break-words' : 'truncate',
                                  notification.status === 'pending'
                                    ? 'text-slate-200'
                                    : 'text-slate-400',
                                )}
                              >
                                {notification.title}
                              </span>
                              {notification.status === 'pending' && (
                                <span className="w-2 h-2 bg-phosphor-500 rounded-full flex-shrink-0" />
                              )}
                            </div>
                            <p
                              className={clsx(
                                'text-xs mt-1',
                                expanded
                                  ? 'whitespace-pre-wrap break-words text-slate-300'
                                  : 'line-clamp-2 text-slate-500',
                              )}
                            >
                              {notification.message}
                            </p>
                            <span className="text-xs text-slate-600 mt-1 block">
                              {notification.created_at
                                ? new Date(
                                    notification.created_at,
                                  ).toLocaleString()
                                : 'Just now'}
                            </span>
                          </div>
                        </button>
                        {href && (
                          <div className="pb-3 pl-12 pr-4">
                            <Link
                              href={href}
                              onClick={() => setIsOpen(false)}
                              className="text-xs text-phosphor-400 hover:text-phosphor-300"
                            >
                              Open
                            </Link>
                          </div>
                        )}
                        <button
                          type="button"
                          onClick={(e) => handleDismiss(e, notification)}
                          className="absolute right-3 top-3 p-1 hover:bg-slate-700 rounded opacity-0 group-hover:opacity-100 focus-visible:opacity-100 transition-opacity"
                          title="Dismiss"
                          aria-label="Dismiss"
                        >
                          <X className="w-4 h-4 text-slate-500" />
                        </button>
                      </div>
                    )
                  })}
                  {notifications.length < total && (
                    <button
                      type="button"
                      onClick={() => void loadMore()}
                      disabled={loadingMore}
                      className="w-full py-3 text-xs text-slate-400 hover:text-slate-200 disabled:text-slate-600"
                    >
                      {loadingMore
                        ? 'Loading...'
                        : `Show more (${total - notifications.length})`}
                    </button>
                  )}
                </>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  )
}
