'use client'

import { Check, Loader2 } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import type { ProgressStep } from './types'

interface EnrichmentProgressStepsProps {
  steps: ProgressStep[]
}

export function EnrichmentProgressSteps({
  steps,
}: EnrichmentProgressStepsProps) {
  return (
    <div className="space-y-1">
      <AnimatePresence mode="popLayout">
        {steps.map((step, index) => (
          <motion.div
            key={step.id}
            initial={{ opacity: 0, x: -10 }}
            animate={{
              opacity: step.status === 'pending' ? 0.4 : 1,
              x: 0,
            }}
            transition={{
              duration: 0.3,
              delay: index * 0.1,
            }}
            className="flex items-center gap-3 py-2 px-3 rounded-md
              transition-colors duration-300"
            style={{
              backgroundColor:
                step.status === 'active'
                  ? 'rgba(59, 130, 246, 0.08)'
                  : 'transparent',
            }}
          >
            {/* Step Icon */}
            <div className="relative w-5 h-5 flex-shrink-0">
              {step.status === 'completed' ? (
                <motion.div
                  initial={{ scale: 0 }}
                  animate={{ scale: 1 }}
                  transition={{ type: 'spring', stiffness: 400, damping: 15 }}
                  className="w-5 h-5 rounded-full bg-phosphor-500/20 flex items-center justify-center"
                >
                  <Check className="w-3 h-3 text-phosphor-400" />
                </motion.div>
              ) : step.status === 'active' ? (
                <Loader2 className="w-5 h-5 text-blue-400 animate-spin" />
              ) : (
                <step.icon className="w-5 h-5 text-slate-600" />
              )}
            </div>

            {/* Step Label */}
            <div className="flex-1 min-w-0">
              <span
                className={`text-sm font-medium transition-colors duration-300 ${
                  step.status === 'completed'
                    ? 'text-slate-300'
                    : step.status === 'active'
                      ? 'text-white'
                      : 'text-slate-500'
                }`}
              >
                {step.status === 'completed' && step.completedLabel
                  ? step.completedLabel
                  : step.label}
              </span>
            </div>
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  )
}
