'use client'

import { AlertTriangle, ArrowLeft } from 'lucide-react'
import Link from 'next/link'
import type { Notification } from '@/lib/api/notifications'

interface BlockerBannerProps {
  taskId: string
  notification: Notification | null
}

export function BlockerBanner({ taskId, notification }: BlockerBannerProps) {
  const title = notification?.title || `Task ${taskId}`
  const severity = notification?.severity || 'error'

  const severityStyles: Record<string, string> = {
    critical: 'border-red-500/30 bg-red-500/5 text-red-400',
    error: 'border-red-500/20 bg-red-500/5 text-red-400',
    warning: 'border-amber-500/20 bg-amber-500/5 text-amber-400',
    info: 'border-blue-500/20 bg-blue-500/5 text-blue-400',
  }

  return (
    <div className={`flex items-center gap-3 px-4 py-2.5 border-b ${severityStyles[severity] || severityStyles.error}`}>
      <Link
        href={`/projects/summitflow/tasks/${taskId}`}
        className="shrink-0 hover:opacity-70 transition-opacity"
      >
        <ArrowLeft className="w-4 h-4" />
      </Link>
      <AlertTriangle className="w-4 h-4 shrink-0" />
      <span className="text-sm font-medium truncate">{title}</span>
      {notification?.message && (
        <span className="text-xs opacity-60 truncate hidden sm:inline">
          — {notification.message}
        </span>
      )}
    </div>
  )
}
