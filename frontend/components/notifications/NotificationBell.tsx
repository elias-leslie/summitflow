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
import { PushNotificationToggle } from './PushNotificationToggle'

interface NotificationBellProps {
  projectId: string
  className?: string
}

const severityIcons = {
  info: Info,
  warning: AlertTriangle,
  error: AlertCircle,
  critical: AlertCircle,
}

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
  const [notifications, setNotifications] = useState<Notification[]>([])
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)

  // Fetch pending count periodically
  useEffect(() => {
    const fetchCount = async () => {
      try {
        const count = await fetchNotificationCount(projectId)
        setPendingCount(count)
      } catch {
        // Silently fail - notifications are optional
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
      const data = await fetchNotifications(projectId, { limit: 10 })
      setNotifications(data.items)
      setPendingCount(data.pending_count)
    } catch {
      setLoadError('Failed to load notifications')
    } finally {
      setLoading(false)
    }
  }, [projectId])

  const handleToggle = () => {
    if (!isOpen) {
      loadNotifications()
    }
    setIsOpen(!isOpen)
  }

  const handleNotificationClick = async (notification: Notification) => {
    if (notification.status === 'pending') {
      try {
        await markNotificationRead(projectId, notification.id)
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

  const handleDismiss = async (e: React.MouseEvent, notificationId: string) => {
    e.stopPropagation()
    try {
      await dismissNotification(projectId, notificationId)
      setNotifications((prev) => prev.filter((n) => n.id !== notificationId))
      setPendingCount((prev) => Math.max(0, prev - 1))
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
        aria-label="Notifications"
        aria-expanded={isOpen}
        aria-haspopup="dialog"
        title="Notifications"
      >
        <Bell className="w-4 h-4" />
        {pendingCount > 0 && (
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
          <div className="absolute right-0 top-full mt-2 w-80 sm:w-96 bg-slate-900 border border-slate-700 rounded-lg shadow-xl z-50 overflow-hidden">
            {/* Header */}
            <div className="flex items-center justify-between px-4 py-3 border-b border-slate-700">
              <h3 className="text-sm font-medium text-slate-200">
                Notifications
              </h3>
              <div className="flex items-center gap-2">
                {pendingCount > 0 && (
                  <>
                    <span className="text-xs text-slate-400">
                      {pendingCount} pending
                    </span>
                    <button
                      type="button"
                      onClick={async () => {
                        try {
                          await dismissAllNotifications(projectId)
                          setNotifications([])
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
                  </>
                )}
                <PushNotificationToggle />
              </div>
            </div>

            {/* Notification List */}
            <div className="max-h-[400px] overflow-y-auto">
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
                notifications.map((notification) => {
                  const Icon = severityIcons[notification.severity]
                  return (
                    <div
                      key={notification.id}
                      role="button"
                      tabIndex={0}
                      onClick={() => handleNotificationClick(notification)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.preventDefault()
                          handleNotificationClick(notification)
                        }
                      }}
                      className={clsx(
                        'group px-4 py-3 border-b border-slate-800 hover:bg-slate-800/50 cursor-pointer transition-colors',
                        notification.status === 'pending' &&
                          'bg-slate-800/30',
                      )}
                    >
                      <div className="flex items-start gap-3">
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
                                'text-sm font-medium truncate',
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
                          <p className="text-xs text-slate-500 mt-1 line-clamp-2">
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
                        <button
                          type="button"
                          onClick={(e) => handleDismiss(e, notification.id)}
                          className="p-1 hover:bg-slate-700 rounded opacity-0 group-hover:opacity-100 transition-opacity"
                          title="Dismiss"
                        >
                          <X className="w-4 h-4 text-slate-500" />
                        </button>
                      </div>
                    </div>
                  )
                })
              )}
            </div>

          </div>
        </>
      )}
    </div>
  )
}
