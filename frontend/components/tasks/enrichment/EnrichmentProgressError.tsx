'use client'

import { AlertCircle, Loader2, RefreshCw } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { useState } from 'react'
import { Button } from '@/components/ui/button'

interface EnrichmentProgressErrorProps {
  error: string | null
  onRetry: () => Promise<void>
}

export function EnrichmentProgressError({
  error,
  onRetry,
}: EnrichmentProgressErrorProps) {
  const [isRetrying, setIsRetrying] = useState(false)

  const handleRetry = async () => {
    setIsRetrying(true)
    await onRetry()
    setIsRetrying(false)
  }

  return (
    <AnimatePresence>
      {error && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: 10 }}
          className="mt-6 p-4 bg-red-950/50 border border-red-800/50 rounded-lg"
        >
          <div className="flex items-start gap-3">
            <AlertCircle className="w-5 h-5 text-red-400 flex-shrink-0 mt-0.5" />
            <div className="flex-1">
              <p className="text-sm text-red-400 font-medium">
                Enrichment Failed
              </p>
              <p className="text-xs text-red-400/70 mt-1">{error}</p>
            </div>
          </div>
          <Button
            variant="outline"
            size="sm"
            className="mt-3 border-red-800/50 text-red-400 hover:bg-red-950/50"
            onClick={handleRetry}
            disabled={isRetrying}
          >
            {isRetrying ? (
              <>
                <Loader2 className="w-3 h-3 mr-2 animate-spin" />
                Retrying...
              </>
            ) : (
              <>
                <RefreshCw className="w-3 h-3 mr-2" />
                Retry Enrichment
              </>
            )}
          </Button>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
