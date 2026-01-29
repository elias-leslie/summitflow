'use client'

import { clsx } from 'clsx'
import {
  CheckCircle,
  ChevronDown,
  ChevronUp,
  Circle,
  Clock,
  Copy,
  FileCode,
  HelpCircle,
  MessageSquare,
} from 'lucide-react'
import { useState } from 'react'
import { buildApiUrl } from '@/lib/api-config'
import { Badge } from '../ui/badge'
import { Button } from '../ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '../ui/card'
import { ScrollArea } from '../ui/scroll-area'

interface CheckpointViewerProps {
  checkpoint: Checkpoint
  className?: string
  onResume?: (resumePrompt: string) => void
}

interface Checkpoint {
  id: string
  project_id: string
  session_id: string
  agent_type: string
  current_action: string | null
  question: string | null
  options: Array<{ label: string; description?: string }> | null
  recommendation: string | null
  completed_steps: string[] | null
  remaining_steps: string[] | null
  files_modified: string[] | null
  decisions_made: Array<{ decision: string; rationale?: string }> | null
  conversation_summary: string | null
  context_snapshot: Record<string, unknown> | null
  tokens_used: number | null
  created_at: string | null
}

export function CheckpointViewer({
  checkpoint,
  className,
  onResume,
}: CheckpointViewerProps) {
  const [showSummary, setShowSummary] = useState(false)
  const [copied, setCopied] = useState(false)
  const [resumePrompt, setResumePrompt] = useState<string | null>(null)
  const [loadingPrompt, setLoadingPrompt] = useState(false)

  const completedSteps = checkpoint.completed_steps || []
  const remainingSteps = checkpoint.remaining_steps || []
  const totalSteps = completedSteps.length + remainingSteps.length
  const progress =
    totalSteps > 0 ? (completedSteps.length / totalSteps) * 100 : 0

  const fetchResumePrompt = async () => {
    if (resumePrompt) return // Already fetched

    setLoadingPrompt(true)
    try {
      const response = await fetch(
        buildApiUrl(
          `/api/projects/${checkpoint.project_id}/checkpoints/${checkpoint.id}/resume`,
        ),
        { method: 'POST' },
      )
      if (response.ok) {
        const data = await response.json()
        setResumePrompt(data.resume_prompt)
      }
    } catch (error) {
      console.error('Failed to fetch resume prompt:', error)
    } finally {
      setLoadingPrompt(false)
    }
  }

  const handleCopyPrompt = async () => {
    if (!resumePrompt) {
      await fetchResumePrompt()
    }
    if (resumePrompt) {
      await navigator.clipboard.writeText(resumePrompt)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
      onResume?.(resumePrompt)
    }
  }

  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return 'Unknown'
    return new Date(dateStr).toLocaleString()
  }

  return (
    <Card className={clsx('overflow-hidden', className)}>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2 text-base">
            <Clock className="h-4 w-4 text-slate-500" />
            Checkpoint
          </CardTitle>
          <Badge variant="secondary" className="text-xs">
            {checkpoint.agent_type}
          </Badge>
        </div>
        <div className="text-xs text-slate-500">
          {formatDate(checkpoint.created_at)}
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* Current Action */}
        {checkpoint.current_action && (
          <div className="space-y-1">
            <div className="text-xs font-medium text-slate-500 uppercase tracking-wide">
              Current Work
            </div>
            <div className="text-sm">{checkpoint.current_action}</div>
          </div>
        )}

        {/* Pending Question */}
        {checkpoint.question && (
          <div className="space-y-2 rounded-lg bg-amber-50 dark:bg-amber-950/30 p-3">
            <div className="flex items-center gap-1.5 text-xs font-medium text-amber-700 dark:text-amber-400">
              <HelpCircle className="h-3.5 w-3.5" />
              Pending Question
            </div>
            <div className="text-sm">{checkpoint.question}</div>
            {checkpoint.options && checkpoint.options.length > 0 && (
              <div className="space-y-1 mt-2">
                <div className="text-xs text-slate-500">Options:</div>
                {checkpoint.options.map((opt, i) => (
                  <div
                    key={i}
                    className="text-sm pl-2 text-slate-600 dark:text-slate-400"
                  >
                    {i + 1}. {opt.label}
                  </div>
                ))}
              </div>
            )}
            {checkpoint.recommendation && (
              <div className="text-xs text-slate-500 mt-2">
                Recommendation: {checkpoint.recommendation}
              </div>
            )}
          </div>
        )}

        {/* Progress */}
        {totalSteps > 0 && (
          <div className="space-y-2">
            <div className="flex justify-between text-xs text-slate-500">
              <span>Progress</span>
              <span>
                {completedSteps.length}/{totalSteps} steps
              </span>
            </div>
            <div className="h-1.5 bg-slate-200 dark:bg-slate-700 rounded-full overflow-hidden">
              <div
                className="h-full bg-phosphor-500 transition-all duration-300"
                style={{ width: `${progress}%` }}
              />
            </div>

            {/* Steps lists */}
            <div className="space-y-2 mt-3">
              {completedSteps.length > 0 && (
                <div className="space-y-1">
                  <div className="text-xs font-medium text-slate-500">
                    Completed
                  </div>
                  <ScrollArea className="max-h-24">
                    {completedSteps.slice(0, 10).map((step, i) => (
                      <div
                        key={i}
                        className="flex items-start gap-1.5 text-xs py-0.5"
                      >
                        <CheckCircle className="h-3 w-3 text-phosphor-500 mt-0.5 flex-shrink-0" />
                        <span className="text-slate-600 dark:text-slate-400">
                          {step}
                        </span>
                      </div>
                    ))}
                    {completedSteps.length > 10 && (
                      <div className="text-xs text-slate-400 pl-4">
                        +{completedSteps.length - 10} more
                      </div>
                    )}
                  </ScrollArea>
                </div>
              )}

              {remainingSteps.length > 0 && (
                <div className="space-y-1">
                  <div className="text-xs font-medium text-slate-500">
                    Remaining
                  </div>
                  <ScrollArea className="max-h-24">
                    {remainingSteps.slice(0, 10).map((step, i) => (
                      <div
                        key={i}
                        className="flex items-start gap-1.5 text-xs py-0.5"
                      >
                        <Circle className="h-3 w-3 text-slate-400 mt-0.5 flex-shrink-0" />
                        <span className="text-slate-500">{step}</span>
                      </div>
                    ))}
                    {remainingSteps.length > 10 && (
                      <div className="text-xs text-slate-400 pl-4">
                        +{remainingSteps.length - 10} more
                      </div>
                    )}
                  </ScrollArea>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Files Modified */}
        {checkpoint.files_modified && checkpoint.files_modified.length > 0 && (
          <div className="space-y-1">
            <div className="flex items-center gap-1.5 text-xs font-medium text-slate-500">
              <FileCode className="h-3.5 w-3.5" />
              Files Modified
            </div>
            <div className="flex flex-wrap gap-1">
              {checkpoint.files_modified.slice(0, 5).map((file, i) => (
                <Badge key={i} variant="outline" className="text-xs font-mono">
                  {file.split('/').pop()}
                </Badge>
              ))}
              {checkpoint.files_modified.length > 5 && (
                <Badge variant="secondary" className="text-xs">
                  +{checkpoint.files_modified.length - 5}
                </Badge>
              )}
            </div>
          </div>
        )}

        {/* Conversation Summary (Collapsible) */}
        {checkpoint.conversation_summary && (
          <div className="space-y-1">
            <button
              onClick={() => setShowSummary(!showSummary)}
              className="flex items-center gap-1.5 text-xs font-medium text-slate-500 hover:text-slate-700 dark:hover:text-slate-300"
            >
              <MessageSquare className="h-3.5 w-3.5" />
              Conversation Summary
              {showSummary ? (
                <ChevronUp className="h-3 w-3" />
              ) : (
                <ChevronDown className="h-3 w-3" />
              )}
            </button>
            {showSummary && (
              <ScrollArea className="max-h-40 rounded border border-slate-200 dark:border-slate-700 p-2">
                <pre className="text-xs whitespace-pre-wrap text-slate-600 dark:text-slate-400">
                  {checkpoint.conversation_summary}
                </pre>
              </ScrollArea>
            )}
          </div>
        )}

        {/* Tokens Used */}
        {checkpoint.tokens_used !== null && checkpoint.tokens_used > 0 && (
          <div className="text-xs text-slate-400">
            Tokens used: {checkpoint.tokens_used.toLocaleString()}
          </div>
        )}

        {/* Resume Button */}
        <Button
          size="sm"
          onClick={handleCopyPrompt}
          disabled={loadingPrompt}
          className="w-full"
        >
          {loadingPrompt ? (
            'Loading...'
          ) : copied ? (
            <>
              <CheckCircle className="h-3.5 w-3.5 mr-1.5" />
              Copied!
            </>
          ) : (
            <>
              <Copy className="h-3.5 w-3.5 mr-1.5" />
              Copy Resume Prompt
            </>
          )}
        </Button>
      </CardContent>
    </Card>
  )
}

export type { Checkpoint }
