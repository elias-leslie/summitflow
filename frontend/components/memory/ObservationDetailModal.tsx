'use client'

import { clsx } from 'clsx'
import {
  Check,
  Clock,
  Copy,
  FileText,
  Loader2,
  Tag,
  X,
  Zap,
} from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { useCallback, useEffect, useState } from 'react'
import { formatTime } from '@/lib/formatters/memory-formatters'
import type { Observation } from './rows'

interface ObservationDetailModalProps {
  observation: Observation | null
  onClose: () => void
}

const TYPE_COLORS: Record<string, string> = {
  error: 'bg-rose-500/15 text-rose-400 border-rose-500/30',
  warning: 'bg-amber-500/15 text-amber-400 border-amber-500/30',
  operational: 'bg-blue-500/15 text-blue-400 border-blue-500/30',
  pattern: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30',
  architecture: 'bg-purple-500/15 text-purple-400 border-purple-500/30',
  decision: 'bg-purple-500/15 text-purple-400 border-purple-500/30',
  refactoring: 'bg-slate-500/15 text-slate-400 border-slate-500/30',
  feature: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30',
  bugfix: 'bg-rose-500/15 text-rose-400 border-rose-500/30',
  discovery: 'bg-cyan-500/15 text-cyan-400 border-cyan-500/30',
  change: 'bg-blue-500/15 text-blue-400 border-blue-500/30',
  default: 'bg-slate-500/15 text-slate-400 border-slate-500/30',
}

interface FullObservation {
  id: string
  project_id: string
  session_id: string
  agent_type: string
  observation_type: string
  title: string
  concepts: string[]
  subtitle?: string
  narrative?: string
  facts?: Record<string, unknown>
  files_read?: string[]
  files_modified?: string[]
  discovery_tokens?: number
  created_at: string
}

export function ObservationDetailModal({
  observation,
  onClose,
}: ObservationDetailModalProps) {
  const [fullData, setFullData] = useState<FullObservation | null>(null)
  const [loading, setLoading] = useState(false)
  const [copied, setCopied] = useState(false)

  // Fetch full observation data
  useEffect(() => {
    if (!observation) {
      setFullData(null)
      return
    }

    const fetchFullData = async () => {
      setLoading(true)
      try {
        const res = await fetch(
          `/api/memory/observations?ids=${observation.id}`,
        )
        if (res.ok) {
          const data = await res.json()
          if (data.observations && data.observations.length > 0) {
            setFullData(data.observations[0])
          } else {
            // Fallback to the observation we already have
            setFullData(observation)
          }
        } else {
          setFullData(observation)
        }
      } catch (error) {
        console.error('Failed to fetch observation details:', error)
        setFullData(observation)
      } finally {
        setLoading(false)
      }
    }

    fetchFullData()
  }, [observation])

  // Handle copy to clipboard
  const handleCopy = useCallback(async () => {
    if (!fullData) return

    const content = `# ${fullData.title}

Type: ${fullData.observation_type}
Time: ${formatTime(fullData.created_at)}

${fullData.narrative || ''}

${
  fullData.facts
    ? `## Facts\n${Object.entries(fullData.facts)
        .map(([k, v]) => `- ${k}: ${v}`)
        .join('\n')}`
    : ''
}

${fullData.files_modified?.length ? `## Files Modified\n${fullData.files_modified.join('\n')}` : ''}
`.trim()

    try {
      await navigator.clipboard.writeText(content)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch (error) {
      console.error('Failed to copy:', error)
    }
  }, [fullData])

  // Close on escape
  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleEscape)
    return () => window.removeEventListener('keydown', handleEscape)
  }, [onClose])

  if (!observation) return null

  const typeColor =
    TYPE_COLORS[observation.observation_type] || TYPE_COLORS.default

  return (
    <AnimatePresence>
      {observation && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="fixed inset-0 bg-slate-950/80 backdrop-blur-sm z-50"
          />

          {/* Modal */}
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 20 }}
            transition={{ type: 'spring', bounce: 0.2, duration: 0.4 }}
            className="fixed inset-x-4 top-[10%] bottom-[10%] md:inset-x-auto md:left-1/2 md:-translate-x-1/2 md:w-full md:max-w-2xl z-50 flex flex-col"
          >
            <div className="flex-1 bg-slate-900 border border-slate-700/50 rounded-xl overflow-hidden flex flex-col shadow-2xl">
              {/* Header */}
              <div className="flex items-center justify-between px-5 py-4 border-b border-slate-700/50 bg-slate-800/50">
                <div className="flex items-center gap-3 min-w-0">
                  <span
                    className={clsx(
                      'text-[11px] font-semibold uppercase px-2.5 py-1 rounded border shrink-0',
                      typeColor,
                    )}
                  >
                    {observation.observation_type}
                  </span>
                  <h2 className="text-lg font-medium text-slate-100 truncate">
                    {observation.title}
                  </h2>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <button
                    onClick={handleCopy}
                    className={clsx(
                      'p-2 rounded-lg transition-colors',
                      copied
                        ? 'bg-emerald-500/15 text-emerald-400'
                        : 'bg-slate-700/50 text-slate-400 hover:text-slate-200 hover:bg-slate-700',
                    )}
                    title="Copy to clipboard"
                  >
                    {copied ? (
                      <Check className="w-4 h-4" />
                    ) : (
                      <Copy className="w-4 h-4" />
                    )}
                  </button>
                  <button
                    onClick={onClose}
                    className="p-2 rounded-lg bg-slate-700/50 text-slate-400 hover:text-slate-200 hover:bg-slate-700 transition-colors"
                  >
                    <X className="w-4 h-4" />
                  </button>
                </div>
              </div>

              {/* Content */}
              <div className="flex-1 overflow-y-auto p-5">
                {loading ? (
                  <div className="flex items-center justify-center py-16 text-slate-500">
                    <Loader2 className="w-5 h-5 animate-spin mr-2" />
                    Loading observation details...
                  </div>
                ) : fullData ? (
                  <div className="space-y-5">
                    {/* Metadata Row */}
                    <div className="flex items-center gap-4 text-sm text-slate-400">
                      <span className="flex items-center gap-1.5">
                        <Clock className="w-4 h-4" />
                        {formatTime(fullData.created_at)}
                      </span>
                      {fullData.discovery_tokens && (
                        <span className="flex items-center gap-1.5">
                          <Zap className="w-4 h-4" />~
                          {fullData.discovery_tokens} tokens
                        </span>
                      )}
                      {fullData.agent_type && (
                        <span className="px-2 py-0.5 rounded bg-slate-700/50 text-slate-400 text-xs">
                          {fullData.agent_type}
                        </span>
                      )}
                    </div>

                    {/* Subtitle */}
                    {fullData.subtitle && (
                      <p className="text-sm text-slate-400 italic">
                        {fullData.subtitle}
                      </p>
                    )}

                    {/* Narrative */}
                    {fullData.narrative && (
                      <div>
                        <h3 className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 mb-2">
                          Narrative
                        </h3>
                        <p className="text-sm text-slate-300 leading-relaxed whitespace-pre-wrap">
                          {fullData.narrative}
                        </p>
                      </div>
                    )}

                    {/* Facts */}
                    {fullData.facts &&
                      Object.keys(fullData.facts).length > 0 && (
                        <div>
                          <h3 className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 mb-2">
                            Facts Extracted
                          </h3>
                          <ul className="space-y-1.5">
                            {Object.entries(fullData.facts).map(
                              ([key, value]) => (
                                <li
                                  key={key}
                                  className="text-sm text-slate-300 pl-4 relative"
                                >
                                  <span className="absolute left-0 text-outrun-500">
                                    -
                                  </span>
                                  <span className="text-slate-500">{key}:</span>{' '}
                                  <span>{String(value)}</span>
                                </li>
                              ),
                            )}
                          </ul>
                        </div>
                      )}

                    {/* Files Modified */}
                    {fullData.files_modified &&
                      fullData.files_modified.length > 0 && (
                        <div>
                          <h3 className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 mb-2 flex items-center gap-1.5">
                            <FileText className="w-3.5 h-3.5" />
                            Files Modified
                          </h3>
                          <div className="flex flex-wrap gap-2">
                            {fullData.files_modified.map((file) => (
                              <span
                                key={file}
                                className="text-[12px] font-mono px-2.5 py-1 rounded bg-slate-700/50 text-slate-300"
                              >
                                {file}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}

                    {/* Concepts */}
                    {fullData.concepts && fullData.concepts.length > 0 && (
                      <div>
                        <h3 className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 mb-2 flex items-center gap-1.5">
                          <Tag className="w-3.5 h-3.5" />
                          Concepts
                        </h3>
                        <div className="flex flex-wrap gap-2">
                          {fullData.concepts.map((concept) => (
                            <span
                              key={concept}
                              className="text-xs px-2.5 py-1 rounded-full bg-outrun-500/10 text-outrun-400 border border-outrun-500/20"
                            >
                              {concept}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="text-center py-16 text-slate-500">
                    <FileText className="w-10 h-10 mx-auto mb-4 opacity-30" />
                    <p>No additional details available</p>
                  </div>
                )}
              </div>

              {/* Footer */}
              <div className="px-5 py-3 border-t border-slate-700/50 bg-slate-800/30">
                <div className="text-[11px] text-slate-500 font-mono">
                  ID: {observation.id}
                </div>
              </div>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  )
}
