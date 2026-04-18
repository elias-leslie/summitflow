'use client'

import clsx from 'clsx'
import { Bot, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'

interface AutonomousToggleProps {
  autonomous?: boolean
  isToggling: boolean
  isRunning: boolean
  onToggle: () => void
}

export function AutonomousToggle({
  autonomous,
  isToggling,
  isRunning,
  onToggle,
}: AutonomousToggleProps) {
  return (
    <Button
      variant="outline"
      className={clsx(
        'gap-2',
        autonomous
          ? 'border-purple-500/30 text-purple-400 bg-purple-500/10'
          : 'border-slate-600 text-slate-400',
      )}
      onClick={onToggle}
      disabled={isToggling || isRunning}
      title={
        autonomous
          ? 'Autonomous execution enabled - task will be picked up by auto-exec when enabled'
          : 'Click to enable autonomous execution for this task'
      }
    >
      {isToggling ? (
        <Loader2 className="h-4 w-4 animate-spin" />
      ) : (
        <Bot className="h-4 w-4" />
      )}
      {autonomous ? 'Autonomous' : 'Manual'}
    </Button>
  )
}
