'use client'

import { ChevronDown, ChevronUp, FileText } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { useMemo, useState } from 'react'

interface DescriptionSectionProps {
  description: string | null | undefined
  collapsedLength?: number
}

export function DescriptionSection({
  description,
  collapsedLength = 200,
}: DescriptionSectionProps) {
  const [isExpanded, setIsExpanded] = useState(false)

  const { shouldCollapse, displayText } = useMemo(() => {
    if (!description) {
      return { shouldCollapse: false, displayText: '' }
    }
    const shouldCollapse = description.length > collapsedLength
    const displayText =
      shouldCollapse && !isExpanded
        ? `${description.slice(0, collapsedLength).trim()}...`
        : description
    return { shouldCollapse, displayText }
  }, [description, collapsedLength, isExpanded])

  if (!description) {
    return null
  }

  return (
    <section>
      <div className="flex items-center gap-2 mb-2">
        <FileText className="w-4 h-4 text-slate-500" />
        <h4 className="text-xs font-mono uppercase tracking-wider text-slate-400">
          Description
        </h4>
      </div>

      <div className="relative">
        <AnimatePresence mode="wait">
          <motion.div
            key={isExpanded ? 'expanded' : 'collapsed'}
            initial={{ opacity: 0.8 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.15 }}
            className="p-4 bg-slate-800/30 border border-slate-800 rounded-lg"
          >
            <p className="text-sm text-slate-300 whitespace-pre-wrap leading-relaxed">
              {displayText}
            </p>

            {shouldCollapse && (
              <button
                onClick={() => setIsExpanded(!isExpanded)}
                className="mt-3 flex items-center gap-1 text-xs text-slate-500 hover:text-slate-400 transition-colors"
              >
                {isExpanded ? (
                  <>
                    <ChevronUp className="w-3 h-3" />
                    Show less
                  </>
                ) : (
                  <>
                    <ChevronDown className="w-3 h-3" />
                    Show more ({description.length - collapsedLength} more
                    chars)
                  </>
                )}
              </button>
            )}
          </motion.div>
        </AnimatePresence>
      </div>
    </section>
  )
}
