'use client'

import { clsx } from 'clsx'
import { Card, CardContent } from '../ui/card'
import { CheckpointHeader } from './checkpoint/CheckpointHeader'
import { ConversationSummary } from './checkpoint/ConversationSummary'
import { FilesModified } from './checkpoint/FilesModified'
import { PendingQuestion } from './checkpoint/PendingQuestion'
import { ProgressSection } from './checkpoint/ProgressSection'
import { ResumeButton } from './checkpoint/ResumeButton'

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
  const completedSteps = checkpoint.completed_steps || []
  const remainingSteps = checkpoint.remaining_steps || []

  return (
    <Card className={clsx('overflow-hidden', className)}>
      <CheckpointHeader
        agentType={checkpoint.agent_type}
        createdAt={checkpoint.created_at}
      />

      <CardContent className="space-y-4">
        {checkpoint.current_action && (
          <div className="space-y-1">
            <div className="text-xs font-medium text-slate-500 uppercase tracking-wide">
              Current Work
            </div>
            <div className="text-sm">{checkpoint.current_action}</div>
          </div>
        )}

        {checkpoint.question && (
          <PendingQuestion
            question={checkpoint.question}
            options={checkpoint.options}
            recommendation={checkpoint.recommendation}
          />
        )}

        <ProgressSection
          completedSteps={completedSteps}
          remainingSteps={remainingSteps}
        />

        {checkpoint.files_modified && (
          <FilesModified files={checkpoint.files_modified} />
        )}

        {checkpoint.conversation_summary && (
          <ConversationSummary summary={checkpoint.conversation_summary} />
        )}

        {checkpoint.tokens_used !== null && checkpoint.tokens_used > 0 && (
          <div className="text-xs text-slate-400">
            Tokens used: {checkpoint.tokens_used.toLocaleString()}
          </div>
        )}

        <ResumeButton
          checkpointId={checkpoint.id}
          projectId={checkpoint.project_id}
          onResume={onResume}
        />
      </CardContent>
    </Card>
  )
}

export type { Checkpoint }
