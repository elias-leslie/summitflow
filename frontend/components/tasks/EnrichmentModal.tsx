import { useEffect } from 'react'
import { Button } from '@/components/ui/button'
import type { Task } from '@/lib/api'
import { EnrichmentProgress } from './EnrichmentProgress'

interface EnrichmentModalProps {
  projectId: string
  task: Task
  onComplete: (task: Task) => void
  onError: (error: unknown) => void
  onDismiss: () => void
}

export function EnrichmentModal({
  projectId,
  task,
  onComplete,
  onError,
  onDismiss,
}: EnrichmentModalProps) {
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onDismiss()
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [onDismiss])

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-slate-900 border border-slate-700 rounded-lg p-6 max-w-md w-full mx-4 shadow-2xl">
        <EnrichmentProgress
          projectId={projectId}
          task={task}
          onComplete={onComplete}
          onError={onError}
        />
        <div className="mt-4 pt-4 border-t border-slate-800 flex justify-end">
          <Button
            variant="ghost"
            size="sm"
            onClick={onDismiss}
            className="text-slate-500 hover:text-slate-300"
          >
            Run in Background
          </Button>
        </div>
      </div>
    </div>
  )
}
