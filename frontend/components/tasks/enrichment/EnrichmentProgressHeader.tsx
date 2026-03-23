'use client'

import { Bot } from 'lucide-react'
import { motion } from 'motion/react'

interface EnrichmentProgressHeaderProps {
  elapsedMs: number
}

export function EnrichmentProgressHeader({
  elapsedMs,
}: EnrichmentProgressHeaderProps) {
  return (
    <div className="flex items-center gap-3 mb-6">
      <div className="relative">
        <Bot className="w-6 h-6 text-phosphor-400" />
        {/* Pulsing indicator */}
        <motion.div
          className="absolute -top-0.5 -right-0.5 w-2.5 h-2.5 rounded-full bg-phosphor-400"
          animate={{
            scale: [1, 1.3, 1],
            opacity: [1, 0.6, 1],
          }}
          transition={{
            duration: 1.5,
            repeat: Infinity,
            ease: 'easeInOut',
          }}
        />
      </div>
      <div>
        <h3 className="text-sm font-mono uppercase tracking-wider text-slate-100">
          Agent Working
        </h3>
        <p className="text-xs text-slate-500">
          Opus 4.5 + Gemini 3 • {Math.round(elapsedMs / 1000)}s elapsed
        </p>
      </div>
    </div>
  )
}
