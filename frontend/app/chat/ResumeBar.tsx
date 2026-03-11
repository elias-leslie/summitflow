'use client'

import { Loader2, RotateCcw } from 'lucide-react'
import { useCallback, useState } from 'react'
import { toast } from 'sonner'
import { buildApiUrl } from '@/lib/api-config'
import { getErrorMessage } from '@/lib/utils'

interface ResumeBarProps {
  projectId: string
  taskId: string
  personaName?: string
}

export function ResumeBar({
  projectId,
  taskId,
  personaName = 'Persona',
}: ResumeBarProps) {
  const [isResuming, setIsResuming] = useState(false)
  const [resumed, setResumed] = useState(false)

  const handleResume = useCallback(async () => {
    setIsResuming(true)
    try {
      const response = await fetch(
        buildApiUrl(`/api/projects/${projectId}/tasks/${taskId}/execute`),
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
        },
      )

      if (!response.ok) {
        const body = await response.json().catch(() => null)
        throw new Error(body?.detail || `Re-run failed (${response.status})`)
      }

      setResumed(true)
      toast.success('Task re-queued', {
        description: `${personaName} will retry this task with your guidance`,
      })
    } catch (err) {
      toast.error('Failed to re-run task', {
        description: getErrorMessage(err, 'Unknown error'),
      })
    } finally {
      setIsResuming(false)
    }
  }, [projectId, taskId, personaName])

  return (
    <div className="flex items-center gap-2 sm:gap-3">
      <span className="text-xs text-slate-500 font-mono truncate hidden sm:inline">
        {resumed
          ? `Queued — ${personaName} will retry`
          : `Chat with ${personaName}, then re-run when ready`}
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
          <RotateCcw className="w-3.5 h-3.5" />
        )}
        {resumed ? 'Queued' : isResuming ? 'Queuing…' : 'Re-run Task'}
      </button>
    </div>
  )
}
