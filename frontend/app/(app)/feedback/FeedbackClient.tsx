'use client'

import { useQuery } from '@tanstack/react-query'
import { MessageSquareWarning, Signal, Flame, Heart, TriangleAlert } from 'lucide-react'
import { motion } from 'motion/react'
import { useState } from 'react'
import { ComponentSummary } from '@/components/feedback/ComponentSummary'
import { FeedbackBoard } from '@/components/feedback/FeedbackBoard'
import { FeedbackStats } from '@/components/feedback/FeedbackStats'
import { TYPE_CONFIG } from '@/components/feedback/feedbackConstants'
import {
  type FeedbackFilters,
  type FeedbackStatusFilter,
  fetchFeedbackItems,
  fetchFeedbackSummary,
} from '@/lib/api/feedback'
import { STALE_GIT, STALE_STANDARD } from '@/lib/polling'

export function FeedbackClient() {
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [filters, setFilters] = useState<FeedbackFilters>({
    status: 'active',
    sort: 'votes',
    limit: 50,
  })

  // Fetch summary
  const { data: summary, isLoading: summaryLoading, error: summaryError } = useQuery({
    queryKey: ['feedback-summary'],
    queryFn: () => fetchFeedbackSummary(),
    staleTime: STALE_GIT,
  })

  // Fetch items with filters
  const { data: itemsData, isLoading: itemsLoading, error: itemsError } = useQuery({
    queryKey: ['feedback-items', filters],
    queryFn: () => fetchFeedbackItems(filters),
    staleTime: STALE_STANDARD,
  })

  const error = summaryError || itemsError
  const activeSignals =
    (summary?.by_status?.open ?? 0) + (summary?.by_status?.acknowledged ?? 0)
  const spotlight = summary?.top_unresolved?.[0]
  const spotlightTone = spotlight
    ? TYPE_CONFIG[spotlight.feedback_type as keyof typeof TYPE_CONFIG]
    : null

  const handleFiltersChange = (partial: Partial<FeedbackFilters>) => {
    setFilters((prev) => ({ ...prev, ...partial }))
  }

  const handleTypeClick = (type: string | undefined) => {
    handleFiltersChange({ feedback_type: type })
  }

  const handleStatusClick = (status: FeedbackStatusFilter | undefined) => {
    handleFiltersChange({ status })
  }

  const handleComponentClick = (componentId: string | undefined) => {
    handleFiltersChange({ component_id: componentId })
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-[1500px] space-y-4 px-4 py-4 md:px-5 lg:px-6">
        <motion.section
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, ease: [0.25, 0.46, 0.45, 0.94] }}
          className="space-y-3"
        >
          <div className="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
            <div className="flex items-center gap-3">
              <MessageSquareWarning className="h-5 w-5 text-rose-300" />
              <div>
                <h1 className="display text-xl font-semibold tracking-tight text-slate-50">
                  Agent Feedback
                </h1>
                <p className="text-sm text-slate-400">
                  Friction, ideas, praise, and unresolved operational signals
                </p>
              </div>
            </div>

            {spotlight && spotlightTone ? (
              <div className="rounded-lg border border-slate-800/70 bg-slate-950/72 px-3 py-2 xl:max-w-sm">
                <div className="flex items-center gap-2 text-[10px] uppercase tracking-[0.14em] text-slate-500">
                  <TriangleAlert className="h-3 w-3 text-rose-300" />
                  Spotlight
                </div>
                <div className="mt-1 text-sm font-medium text-slate-100">
                  {spotlight.title}
                </div>
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  <span
                    className={`rounded-full border px-2 py-0.5 text-[10px] uppercase tracking-[0.14em] ${spotlightTone.bg} ${spotlightTone.color} ${spotlightTone.border}`}
                  >
                    {spotlightTone.label}
                  </span>
                  <span className="rounded-full border border-amber-500/20 bg-amber-500/10 px-2 py-0.5 text-[10px] uppercase tracking-[0.14em] text-amber-300">
                    {spotlight.vote_count} votes
                  </span>
                  <span className="text-[10px] text-slate-500">{spotlight.component_id}</span>
                </div>
              </div>
            ) : null}
          </div>

          {summary ? (
            <div className="grid gap-2 sm:grid-cols-3">
              <div className="rounded-lg border border-slate-800/80 bg-slate-950/72 px-3 py-2">
                <div className="flex items-center gap-2.5">
                  <Signal className="h-3.5 w-3.5 text-slate-400" />
                  <div className="flex items-baseline gap-2">
                    <span className="font-mono text-lg font-bold tabular-nums text-slate-50">
                      {summary.total.toLocaleString()}
                    </span>
                    <span className="text-[10px] uppercase tracking-[0.14em] text-slate-500">
                      Total
                    </span>
                  </div>
                </div>
              </div>
              <div className="rounded-lg border border-rose-500/20 bg-rose-500/10 px-3 py-2">
                <div className="flex items-center gap-2.5">
                  <Flame className="h-3.5 w-3.5 text-rose-400" />
                  <div className="flex items-baseline gap-2">
                    <span className="font-mono text-lg font-bold tabular-nums text-slate-50">
                      {activeSignals.toLocaleString()}
                    </span>
                    <span className="text-[10px] uppercase tracking-[0.14em] text-rose-200/70">
                      Active
                    </span>
                  </div>
                </div>
              </div>
              <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/10 px-3 py-2">
                <div className="flex items-center gap-2.5">
                  <Heart className="h-3.5 w-3.5 text-emerald-400" />
                  <div className="flex items-baseline gap-2">
                    <span className="font-mono text-lg font-bold tabular-nums text-slate-50">
                      {(summary.by_type?.praise ?? 0).toLocaleString()}
                    </span>
                    <span className="text-[10px] uppercase tracking-[0.14em] text-emerald-200/70">
                      Praise
                    </span>
                  </div>
                </div>
              </div>
            </div>
          ) : null}
        </motion.section>

        {error && (
          <div className="rounded-[1.35rem] border border-rose-500/20 bg-rose-500/10 p-4 text-sm text-rose-300">
            Failed to load feedback data. Verify the backend is running.
          </div>
        )}

        <motion.section
          initial={{ opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{
            duration: 0.4,
            delay: 0.08,
            ease: [0.25, 0.46, 0.45, 0.94],
          }}
          className="space-y-4"
        >
          <FeedbackBoard
            items={itemsData?.items ?? []}
            total={itemsData?.total ?? 0}
            isLoading={itemsLoading}
            filters={filters}
            onFiltersChange={handleFiltersChange}
            onItemClick={setSelectedId}
            selectedId={selectedId}
          />
          <FeedbackStats
            summary={summary}
            isLoading={summaryLoading}
            activeType={filters.feedback_type}
            activeStatus={filters.status}
            onTypeClick={handleTypeClick}
            onStatusClick={handleStatusClick}
          />

          <ComponentSummary
            summary={summary}
            isLoading={summaryLoading}
            activeComponent={filters.component_id}
            onComponentClick={handleComponentClick}
          />
        </motion.section>
      </div>
    </div>
  )
}
