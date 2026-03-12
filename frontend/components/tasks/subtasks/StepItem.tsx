'use client'

import {
  Braces,
  Check,
  CheckSquare,
  ChevronDown,
  ChevronRight,
  Copy,
  Loader2,
  Square,
} from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { useCallback, useEffect, useState } from 'react'
import type { Step } from '@/lib/api/tasks'
import { FEEDBACK_TIMEOUT } from '@/lib/polling'
import { type SpecRecord, SpecRenderer } from './SpecRenderer'

export interface StepItemProps {
  step: Step
  index: number
  isOptimisticallyUpdated: boolean
  onToggle: (stepNumber: number, passes: boolean) => void
  isUpdating: boolean
  isActive?: boolean
}

export function StepItem({
  step,
  index,
  isOptimisticallyUpdated,
  onToggle,
  isUpdating,
  isActive = false,
}: StepItemProps) {
  // Auto-expand spec for active step
  const [isSpecExpanded, setIsSpecExpanded] = useState(isActive)
  const [copied, setCopied] = useState(false)
  const passes = isOptimisticallyUpdated ? !step.passes : step.passes
  const hasSpec = step.spec && Object.keys(step.spec).length > 0

  // Expand spec when step becomes active
  useEffect(() => {
    if (isActive && hasSpec) {
      setIsSpecExpanded(true)
    }
  }, [isActive, hasSpec])

  const handleCopy = useCallback(async () => {
    if (!step.spec) return
    await navigator.clipboard.writeText(JSON.stringify(step.spec, null, 2))
    setCopied(true)
    setTimeout(() => setCopied(false), FEEDBACK_TIMEOUT)
  }, [step.spec])

  return (
    <motion.li
      initial={{ opacity: 0, x: -8 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ delay: index * 0.03 }}
      className={`group relative ${isActive ? 'z-10' : ''}`}
    >
      {/* Active step indicator - animated border */}
      {isActive && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="absolute -inset-2 bg-gradient-to-r from-blue-500/10 to-purple-500/10 rounded-lg border border-blue-500/30"
        >
          <div className="absolute inset-0 bg-blue-500/5 animate-pulse rounded-lg" />
        </motion.div>
      )}
      <div className="flex items-start gap-2.5">
        <button
          type="button"
          onClick={() => onToggle(step.step_number, !passes)}
          disabled={isUpdating}
          className="mt-0.5 flex-shrink-0 focus:outline-none focus:ring-1 focus:ring-blue-500/50 rounded"
          aria-label={passes ? 'Mark step incomplete' : 'Mark step complete'}
        >
          {isUpdating ? (
            <Loader2 className="w-3.5 h-3.5 animate-spin text-slate-500" />
          ) : passes ? (
            <motion.div
              initial={{ scale: 0.8 }}
              animate={{ scale: 1 }}
              transition={{ type: 'spring', stiffness: 400, damping: 15 }}
            >
              <CheckSquare className="w-3.5 h-3.5 text-phosphor-400" />
            </motion.div>
          ) : (
            <Square className="w-3.5 h-3.5 text-slate-600 group-hover:text-slate-400 transition-colors" />
          )}
        </button>
        <div className="flex-1 min-w-0">
          <div className="flex items-start gap-2">
            <span className="text-slate-600 text-2xs font-mono flex-shrink-0 w-4 text-right">
              {step.step_number}.
            </span>
            <span
              className={`text-xs transition-all duration-200 ${
                passes
                  ? 'text-slate-600 line-through decoration-slate-700'
                  : isActive
                    ? 'text-slate-200 font-medium'
                    : 'text-slate-400'
              }`}
            >
              {step.description}
            </span>
            {isActive && (
              <motion.span
                initial={{ opacity: 0, scale: 0.8 }}
                animate={{ opacity: 1, scale: 1 }}
                className="flex-shrink-0 flex items-center gap-1 px-1.5 py-0.5 rounded bg-blue-500/20 text-blue-400 border border-blue-500/30"
              >
                <Loader2 className="w-3 h-3 animate-spin" />
                <span className="text-2xs font-semibold">Running</span>
              </motion.span>
            )}
            {hasSpec && (
              <button
                type="button"
                onClick={() => setIsSpecExpanded(!isSpecExpanded)}
                data-testid={`spec-btn-${step.step_number}`}
                className={`flex-shrink-0 flex items-center gap-1 px-1.5 py-0.5 rounded transition-all duration-150 ${
                  isSpecExpanded
                    ? 'bg-blue-500/15 text-blue-400'
                    : 'bg-slate-800/60 text-slate-500 hover:bg-slate-700/60 hover:text-blue-400'
                }`}
                aria-label={isSpecExpanded ? 'Hide spec' : 'Show spec'}
              >
                <Braces className="w-3 h-3" />
                <span className="text-2xs font-medium">spec</span>
                {isSpecExpanded ? (
                  <ChevronDown className="w-3.5 h-3.5" />
                ) : (
                  <ChevronRight className="w-3.5 h-3.5" />
                )}
              </button>
            )}
          </div>
          <AnimatePresence>
            {isSpecExpanded && hasSpec && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: 'auto', opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                transition={{ duration: 0.15 }}
                className="overflow-hidden"
              >
                <div className="mt-2 ml-6 relative group/spec">
                  {/* Copy button - more visible on hover */}
                  <button
                    type="button"
                    onClick={handleCopy}
                    className={`absolute top-2 right-2 p-1.5 rounded-md transition-all duration-150 z-10 ${
                      copied
                        ? 'bg-phosphor-500/20 text-phosphor-400'
                        : 'bg-slate-700/80 text-slate-400 opacity-60 group-hover/spec:opacity-100 hover:bg-slate-600 hover:text-slate-200'
                    }`}
                    aria-label="Copy spec"
                  >
                    {copied ? (
                      <Check className="w-3.5 h-3.5" />
                    ) : (
                      <Copy className="w-3.5 h-3.5" />
                    )}
                  </button>
                  {/* Spec content with left accent border */}
                  <div className="bg-slate-900/80 border border-slate-700/50 border-l-2 border-l-blue-500/40 rounded-md shadow-inner overflow-hidden">
                    <div className="p-3 pr-10">
                      <SpecRenderer spec={step.spec as SpecRecord} />
                    </div>
                  </div>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>
    </motion.li>
  )
}
