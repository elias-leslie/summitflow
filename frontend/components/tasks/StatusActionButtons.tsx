'use client'

import { CheckCircle2, Square } from 'lucide-react'
import { Button } from '@/components/ui/button'
import type { TaskStatus } from '@/lib/api/tasks'

interface StatusActionButtonsProps {
  status: TaskStatus
  onStatusChange: (status: TaskStatus) => Promise<void>
}

export function StatusActionButtons({
  status,
  onStatusChange,
}: StatusActionButtonsProps) {
  return (
    <>
      {status === 'running' && (
        <Button
          variant="outline"
          className="gap-2 border-red-500/30 text-red-400 hover:bg-red-500/10"
          onClick={() => void onStatusChange('paused')}
        >
          <Square className="h-4 w-4" />
          Pause
        </Button>
      )}
      {status === 'completed' && (
        <Button
          variant="outline"
          className="gap-2 border-phosphor-500/30 text-phosphor-400"
          disabled
        >
          <CheckCircle2 className="h-4 w-4" />
          Completed
        </Button>
      )}
    </>
  )
}
