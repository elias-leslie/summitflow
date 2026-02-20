'use client'

import { Play } from 'lucide-react'
import { useCallback, useState } from 'react'
import { toast } from 'sonner'
import { getApiBaseUrl } from '@/lib/api-config'

interface ResumeBarProps {
  taskId: string
}

export function ResumeBar({ taskId }: ResumeBarProps) {
  const [isResuming, setIsResuming] = useState(false)

  const handleResume = useCallback(async () => {
    setIsResuming(true)
    try {
      const apiBase = getApiBaseUrl()
      const response = await fetch(
        `${apiBase}/api/projects/summitflow/tasks/${taskId}/resume`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
        },
      )

      if (!response.ok) {
        const body = await response.json().catch(() => null)
        throw new Error(body?.detail || `Resume failed (${response.status})`)
      }

      toast.success('Task resumed', {
        description: `Task ${taskId} moved back to queue`,
      })
    } catch (err) {
      toast.error('Failed to resume task', {
        description: err instanceof Error ? err.message : 'Unknown error',
      })
    } finally {
      setIsResuming(false)
    }
  }, [taskId])

  return (
    <div className="flex items-center justify-between px-4 py-3 border-t border-slate-700/50 bg-slate-900/50">
      <span className="text-xs text-muted-foreground">
        Give Johnny direction, then resume the task
      </span>
      <button
        onClick={handleResume}
        disabled={isResuming}
        className="flex items-center gap-2 px-4 py-1.5 text-sm font-medium rounded-md bg-emerald-600 hover:bg-emerald-500 text-white disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
      >
        <Play className="w-3.5 h-3.5" />
        {isResuming ? 'Resuming...' : 'Resume Task'}
      </button>
    </div>
  )
}
