'use client'

import { ExternalLink, ThumbsUp } from 'lucide-react'
import type { FeedbackItemWithVotes } from '@/lib/api/feedback'

// ─── Constants ───────────────────────────────────────────────────

const STATUS_LABELS: Record<string, string> = {
  active: 'Active',
  open: 'Open',
  acknowledged: 'Acknowledged',
  resolved: 'Resolved',
  wont_fix: "Won't Fix",
  archived: 'Archived',
}

// ─── Metric Box ──────────────────────────────────────────────────

function MetricBox({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded bg-slate-950/50 px-2 py-1.5">
      <div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">
        {label}
      </div>
      <div className="truncate text-xs text-slate-200 capitalize">{value}</div>
    </div>
  )
}

// ─── Component ───────────────────────────────────────────────────

interface FeedbackDetailBodyProps {
  item: FeedbackItemWithVotes
}

export function FeedbackDetailBody({ item }: FeedbackDetailBodyProps) {
  return (
    <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
      {/* Description */}
      {item.description && (
        <div>
          <h3 className="text-[10px] uppercase tracking-[0.14em] text-slate-500 mb-1.5">
            Description
          </h3>
          <p className="text-xs text-slate-300 whitespace-pre-wrap leading-relaxed">
            {item.description}
          </p>
        </div>
      )}

      {/* Metadata grid */}
      <div className="grid grid-cols-2 gap-1.5">
        <MetricBox
          label="Status"
          value={STATUS_LABELS[item.status] ?? item.status}
        />
        <MetricBox label="Votes" value={String(item.vote_count)} />
        <MetricBox label="Project" value={item.project_id} />
        <MetricBox
          label="Created"
          value={new Date(item.created_at).toLocaleDateString()}
        />
        {item.agent_slug && (
          <MetricBox label="Agent" value={item.agent_slug} />
        )}
        {item.model_used && (
          <MetricBox label="Model" value={item.model_used} />
        )}
        {item.severity && (
          <MetricBox label="Severity" value={item.severity} />
        )}
        {item.linked_task_id && (
          <div className="min-w-0 rounded bg-slate-950/50 px-2 py-1.5">
            <div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">
              Linked Task
            </div>
            <div className="flex items-center gap-1">
              <span className="truncate text-xs font-mono text-phosphor-400">
                {item.linked_task_id}
              </span>
              <ExternalLink className="w-3 h-3 text-phosphor-500 shrink-0" />
            </div>
          </div>
        )}
      </div>

      {/* Resolution note */}
      {item.resolution_note && (
        <div className="p-3 rounded-lg bg-emerald-500/8 border border-emerald-500/20">
          <h3 className="text-[10px] uppercase tracking-[0.14em] text-emerald-400 mb-1">
            Resolution
          </h3>
          <p className="text-xs text-slate-300">{item.resolution_note}</p>
          {item.resolved_at && (
            <p className="text-[11px] text-slate-500 mt-1">
              {new Date(item.resolved_at).toLocaleDateString()}
            </p>
          )}
        </div>
      )}

      {/* Votes */}
      <div>
        <h3 className="text-[10px] uppercase tracking-[0.14em] text-slate-500 mb-2 flex items-center gap-1.5">
          <ThumbsUp className="w-3 h-3" />
          Votes ({item.votes?.length ?? 0})
        </h3>
        {item.votes && item.votes.length > 0 ? (
          <div className="space-y-1.5">
            {item.votes.map((vote) => (
              <div
                key={vote.id}
                className="rounded border border-slate-800/60 bg-slate-900/40 px-3 py-2"
              >
                <div className="flex items-start gap-2">
                  <ThumbsUp className="w-3 h-3 text-slate-600 mt-0.5 shrink-0" />
                  <div className="flex-1 min-w-0">
                    {vote.comment && (
                      <p className="text-xs text-slate-300 mb-1">
                        {vote.comment}
                      </p>
                    )}
                    <div className="flex items-center gap-2 text-[11px] text-slate-600">
                      {vote.agent_slug && <span>{vote.agent_slug}</span>}
                      <span>
                        {new Date(vote.created_at).toLocaleDateString()}
                      </span>
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-[11px] text-slate-600">No votes yet</p>
        )}
      </div>
    </div>
  )
}
