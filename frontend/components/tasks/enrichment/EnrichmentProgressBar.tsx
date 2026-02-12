'use client'

import { motion } from 'motion/react'

interface EnrichmentProgressBarProps {
  completedCount: number
  totalSteps: number
}

export function EnrichmentProgressBar({
  completedCount,
  totalSteps,
}: EnrichmentProgressBarProps) {
  return (
    <div className="mt-6">
      <div className="h-1 bg-slate-800 rounded-full overflow-hidden">
        <motion.div
          className="h-full bg-gradient-to-r from-phosphor-600 to-blue-500 rounded-full"
          initial={{ width: 0 }}
          animate={{ width: `${(completedCount / totalSteps) * 100}%` }}
          transition={{ duration: 0.4, ease: 'easeOut' }}
        />
      </div>
      <div className="flex justify-between mt-2">
        <span className="text-xs text-slate-500">
          {completedCount}/{totalSteps} steps
        </span>
        <span className="text-xs text-slate-500">
          {Math.round((completedCount / totalSteps) * 100)}% complete
        </span>
      </div>
    </div>
  )
}
