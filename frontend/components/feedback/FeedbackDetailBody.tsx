'use client'

import { ExternalLink, ThumbsUp } from 'lucide-react'
import type { FeedbackItemWithVotes } from '@/lib/api/feedback'

// ============================================================================
// Constants
// ============================================================================

const STATUS_LABELS: Record<string, string> = {
  active: 'Active',
  open: 'Open',
  acknowledged: 'Acknowledged',
  resolved: 'Resolved',
  wont_fix: "Won't Fix",
  archived: 'Archived',
}

// ============================================================================
// Helpers
// ============================================================================

function MetadataItem({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span className="text-2xs text-slate-500">{label}</span>
      <p className="text-xs text-slate-300 mt-0.5 capitalize">{value}</p>
    </div>
  )
}

// ============================================================================
// Component
// ============================================================================

interface FeedbackDetailBodyProps {
  item: FeedbackItemWithVotes
}

export function FeedbackDetailBody({ item }: FeedbackDetailBodyProps) {
  return (
    <div className="flex-1 overflow-y-auto px-5 py-4 space-y-5">
      {/* Description */}
      {item.description && (
        <div>
          <h3 className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-2">
            Description
          </h3>
          <p className="text-sm text-slate-300 whitespace-pre-wrap leading-relaxed">
            {item.description}
          </p>
        </div>
      )}

      {/* Metadata */}
      <div className="grid grid-cols-2 gap-3">
        <MetadataItem label="Status" value={STATUS_LABELS[item.status] ?? item.status} />
        <MetadataItem label="Votes" value={String(item.vote_count)} />
        <MetadataItem label="Project" value={item.project_id} />
        <MetadataItem label="Created" value={new Date(item.created_at).toLocaleDateString()} />
        {item.agent_slug && <MetadataItem label="Agent" value={item.agent_slug} />}
        {item.model_used && <MetadataItem label="Model" value={item.model_used} />}
        {item.severity && <MetadataItem label="Severity" value={item.severity} />}
        {item.linked_task_id && (
          <div>
            <span className="text-2xs text-slate-500">Linked Task</span>
            <div className="flex items-center gap-1 mt-0.5">
              <span className="mono text-xs text-phosphor-400">{item.linked_task_id}</span>
              <ExternalLink className="w-3 h-3 text-phosphor-500" />
            </div>
          </div>
        )}
      </div>

      {/* Resolution note */}
      {item.resolution_note && (
        <div className="p-3 rounded-lg bg-emerald-500/5 border border-emerald-500/20">
          <h3 className="text-xs font-medium text-emerald-400 mb-1">Resolution</h3>
          <p className="text-sm text-slate-300">{item.resolution_note}</p>
          {item.resolved_at && (
            <p className="text-2xs text-slate-500 mt-1">
              {new Date(item.resolved_at).toLocaleDateString()}
            </p>
          )}
        </div>
      )}

      {/* Votes */}
      <div>
        <h3 className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-3 flex items-center gap-2">
          <ThumbsUp className="w-3 h-3" />
          Votes ({item.votes?.length ?? 0})
        </h3>
        {item.votes && item.votes.length > 0 ? (
          <div className="space-y-2">
            {item.votes.map((vote) => (
              <div
                key={vote.id}
                className="flex items-start gap-3 p-2.5 rounded-md bg-slate-800/40"
              >
                <ThumbsUp className="w-3 h-3 text-slate-500 mt-0.5 flex-shrink-0" />
                <div className="flex-1 min-w-0">
                  {vote.comment && (
                    <p className="text-xs text-slate-300 mb-1">{vote.comment}</p>
                  )}
                  <div className="flex items-center gap-2 text-2xs text-slate-500">
                    {vote.agent_slug && <span>{vote.agent_slug}</span>}
                    <span>{new Date(vote.created_at).toLocaleDateString()}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-xs text-slate-600">No votes yet</p>
        )}
      </div>
    </div>
  )
}
