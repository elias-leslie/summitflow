'use client'

import { AlertTriangle, ArrowLeft } from 'lucide-react'
import Link from 'next/link'
import type { Notification } from '@/lib/api/notifications'

interface BlockerBannerProps {
  taskId: string
  notification: Notification | null
}

const severityStyles: Record<string, string> = {
  critical:
    'border-outrun-500/30 bg-outrun-500/5 text-outrun-400 shadow-[inset_0_-1px_0_rgba(255,0,102,0.15)]',
  error:
    'border-outrun-500/20 bg-outrun-500/5 text-outrun-300 shadow-[inset_0_-1px_0_rgba(255,0,102,0.1)]',
  warning:
    'border-sunset-orange/20 bg-sunset-orange/5 text-amber-400 shadow-[inset_0_-1px_0_rgba(255,102,0,0.1)]',
  info: 'border-phosphor-500/20 bg-phosphor-500/5 text-phosphor-400 shadow-[inset_0_-1px_0_rgba(0,245,255,0.1)]',
}

export function BlockerBanner({ taskId, notification }: BlockerBannerProps) {
  const title = notification?.title || `Task ${taskId}`
  const severity = notification?.severity || 'error'
  const styles = severityStyles[severity] || severityStyles.error

  return (
    <div
      className={`flex items-center gap-3 px-4 py-2.5 border-b animate-fade-in ${styles}`}
    >
      <Link
        href={`/projects/summitflow/tasks/${taskId}`}
        className="shrink-0 text-current hover:text-outrun-400 transition-colors"
        aria-label="Back to task"
      >
        <ArrowLeft className="w-4 h-4" />
      </Link>
      <AlertTriangle className="w-4 h-4 shrink-0 animate-pulse" />
      <span className="text-sm font-medium font-display truncate">
        {title}
      </span>
      {notification?.message && (
        <span className="text-xs opacity-50 truncate hidden sm:inline font-mono">
          — {notification.message}
        </span>
      )}
    </div>
  )
}
