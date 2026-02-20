'use client'

import { Loader2, Play } from 'lucide-react'
import { useCallback, useState } from 'react'
import { toast } from 'sonner'
import { getApiBaseUrl } from '@/lib/api-config'

interface ResumeBarProps {
  taskId: string
}

export function ResumeBar({ taskId }: ResumeBarProps) {
  const [isResuming, setIsResuming] = useState(false)
  const [resumed, setResumed] = useState(false)

  const handleResume = useCallback(async () => {
    setIsResuming(true)
    try {
      const apiBase = getApiBaseUrl()
      const response = await fetch(
        `${apiBase}/api/projects/summitflow/tasks/${taskId}/execute`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
        },
      )

      if (!response.ok) {
        const body = await response.json().catch(() => null)
        throw new Error(body?.detail || `Resume failed (${response.status})`)
      }

      setResumed(true)
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
    <div className="flex items-center gap-2 sm:gap-3 animate-slide-up">
      <span className="text-xs text-slate-500 font-mono truncate hidden sm:inline">
        {resumed
          ? 'Task queued — Johnny is on it'
          : 'Give Johnny direction, then resume'}
      </span>
      <button
        type="button"
        onClick={handleResume}
        disabled={isResuming || resumed}
        className="flex items-center gap-1.5 sm:gap-2 px-3 sm:px-4 py-1.5 text-sm font-medium font-display rounded-md bg-phosphor-600 hover:bg-phosphor-500 text-slate-950 disabled:opacity-40 disabled:cursor-not-allowed transition-all hover:shadow-[0_0_12px_rgba(0,245,255,0.3)] whitespace-nowrap flex-shrink-0"
      >
        {isResuming ? (
          <Loader2 className="w-3.5 h-3.5 animate-spin" />
        ) : (
          <Play className="w-3.5 h-3.5" />
        )}
        {resumed ? 'Resumed' : isResuming ? 'Resuming…' : 'Resume'}
      </button>
    </div>
  )
}
