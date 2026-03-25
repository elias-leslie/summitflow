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
      <div className="mx-auto max-w-[1500px] space-y-5 px-4 py-5 md:px-5 lg:px-6">
        <motion.section
          initial={{ opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, ease: [0.25, 0.46, 0.45, 0.94] }}
          className="panel-glass px-4 py-4 md:px-5"
        >
          <div className="space-y-4">
            <div className="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
              <div className="flex items-start gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-2xl border border-rose-500/20 bg-rose-500/10">
                  <MessageSquareWarning className="h-5 w-5 text-rose-300" />
                </div>
                <div>
                  <div className="eyebrow">Agent signals</div>
                  <h1 className="display mt-1.5 text-2xl font-semibold tracking-tight text-slate-50 lg:text-3xl">
                    Agent feedback
                  </h1>
                  <p className="mt-1.5 max-w-3xl text-sm leading-relaxed text-slate-300">
                    Surface friction, ideas, praise, and unresolved operational
                    pain, with the live feedback stream moved up above the fold.
                  </p>
                </div>
              </div>

              {spotlight && spotlightTone ? (
                <div className="rounded-[1.2rem] border border-slate-800/70 bg-slate-950/72 px-4 py-3 xl:max-w-sm">
                  <div className="flex items-center gap-2 text-[10px] uppercase tracking-[0.18em] text-slate-500">
                    <TriangleAlert className="h-3.5 w-3.5 text-rose-300" />
                    Spotlight
                  </div>
                  <div className="mt-2 text-sm font-medium text-slate-100">
                    {spotlight.title}
                  </div>
                  <div className="mt-2 flex flex-wrap gap-2">
                    <span
                      className={`rounded-full border px-2.5 py-1 text-[10px] uppercase tracking-[0.16em] ${spotlightTone.bg} ${spotlightTone.color} ${spotlightTone.border}`}
                    >
                      {spotlightTone.label}
                    </span>
                    <span className="rounded-full border border-amber-500/20 bg-amber-500/10 px-2.5 py-1 text-[10px] uppercase tracking-[0.16em] text-amber-300">
                      {spotlight.vote_count} votes
                    </span>
                  </div>
                  <div className="mt-1 text-[11px] text-slate-500">
                    {spotlight.component_id}
                  </div>
                </div>
              ) : null}
            </div>

            {summary ? (
              <div className="grid gap-2 sm:grid-cols-3">
                <div className="rounded-[1.15rem] border border-slate-800/80 bg-slate-950/72 px-3.5 py-3">
                  <div className="flex items-center gap-3">
                    <div className="rounded-xl bg-slate-800/60 p-2 ring-1 ring-white/5">
                      <Signal className="h-4 w-4 text-slate-400" />
                    </div>
                    <div>
                      <div className="font-mono text-2xl font-bold tabular-nums text-slate-50">
                        {summary.total.toLocaleString()}
                      </div>
                      <div className="mt-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">
                        Total signals
                      </div>
                    </div>
                  </div>
                </div>
                <div className="rounded-[1.15rem] border border-rose-500/20 bg-rose-500/10 px-3.5 py-3">
                  <div className="flex items-center gap-3">
                    <div className="rounded-xl bg-rose-500/15 p-2 ring-1 ring-rose-500/10">
                      <Flame className="h-4 w-4 text-rose-400" />
                    </div>
                    <div>
                      <div className="font-mono text-2xl font-bold tabular-nums text-slate-50">
                        {activeSignals.toLocaleString()}
                      </div>
                      <div className="mt-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-rose-200/70">
                        Active attention
                      </div>
                    </div>
                  </div>
                </div>
                <div className="rounded-[1.15rem] border border-emerald-500/20 bg-emerald-500/10 px-3.5 py-3">
                  <div className="flex items-center gap-3">
                    <div className="rounded-xl bg-emerald-500/15 p-2 ring-1 ring-emerald-500/10">
                      <Heart className="h-4 w-4 text-emerald-400" />
                    </div>
                    <div>
                      <div className="font-mono text-2xl font-bold tabular-nums text-slate-50">
                        {(summary.by_type?.praise ?? 0).toLocaleString()}
                      </div>
                      <div className="mt-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-emerald-200/70">
                        Praise signals
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            ) : null}
          </div>
        </motion.section>

        <motion.section
          initial={{ opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{
            duration: 0.4,
            delay: 0.06,
            ease: [0.25, 0.46, 0.45, 0.94],
          }}
          className="space-y-3"
        >
          <div>
            <h2 className="display text-sm font-semibold uppercase tracking-[0.16em] text-slate-300">
              Feedback stream
            </h2>
            <p className="mt-0.5 text-xs text-slate-500">
              Filter, review, and resolve the underlying signals.
            </p>
          </div>
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
