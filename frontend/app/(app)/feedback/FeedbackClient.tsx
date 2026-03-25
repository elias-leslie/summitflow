'use client'

import { useQuery } from '@tanstack/react-query'
import { MessageSquareWarning, Sparkles, TriangleAlert } from 'lucide-react'
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
      <div className="mx-auto max-w-[1500px] space-y-6 px-4 py-6 md:px-6 lg:px-8">
        <motion.section
          initial={{ opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, ease: [0.25, 0.46, 0.45, 0.94] }}
          className="card-elevated hero-glow relative overflow-hidden px-6 py-6 md:px-8 md:py-8"
        >
          <div className="pointer-events-none absolute inset-y-0 right-0 w-[34%] bg-[radial-gradient(circle_at_top_right,rgba(244,63,94,0.16),transparent_60%)] opacity-80" />
          <div className="grid gap-6 xl:grid-cols-[minmax(0,1.25fr)_360px]">
            <div className="relative z-10 space-y-6">
              <div className="flex items-start gap-3">
                <div className="flex h-12 w-12 items-center justify-center rounded-2xl border border-rose-500/20 bg-rose-500/10">
                  <MessageSquareWarning className="h-6 w-6 text-rose-300" />
                </div>
                <div>
                  <div className="eyebrow">Agent signals</div>
                  <h1 className="display mt-2 text-4xl font-semibold tracking-tight text-slate-50">
                    Agent feedback
                  </h1>
                  <p className="mt-2 max-w-3xl text-sm leading-relaxed text-slate-300 sm:text-base">
                    Surface friction, ideas, praise, and unresolved operational
                    pain in a layout that makes the loudest problems obvious.
                  </p>
                </div>
              </div>

              {summary ? (
                <div className="grid gap-3 sm:grid-cols-3">
                  <div className="rounded-[1.35rem] border border-slate-700/70 bg-slate-950/60 px-4 py-4">
                    <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">
                      Total signals
                    </div>
                    <div className="mt-3 font-mono text-3xl text-slate-50">
                      {summary.total}
                    </div>
                    <div className="mt-1 text-xs text-slate-400">
                      All recorded feedback items.
                    </div>
                  </div>
                  <div className="rounded-[1.35rem] border border-rose-500/20 bg-rose-500/10 px-4 py-4">
                    <div className="text-[11px] uppercase tracking-[0.18em] text-rose-200/70">
                      Active attention
                    </div>
                    <div className="mt-3 font-mono text-3xl text-slate-50">
                      {activeSignals}
                    </div>
                    <div className="mt-1 text-xs text-rose-100/70">
                      Open and acknowledged items.
                    </div>
                  </div>
                  <div className="rounded-[1.35rem] border border-emerald-500/20 bg-emerald-500/10 px-4 py-4">
                    <div className="text-[11px] uppercase tracking-[0.18em] text-emerald-200/70">
                      Praise signals
                    </div>
                    <div className="mt-3 font-mono text-3xl text-slate-50">
                      {summary.by_type?.praise ?? 0}
                    </div>
                    <div className="mt-1 text-xs text-emerald-100/70">
                      Positive reinforcement worth preserving.
                    </div>
                  </div>
                </div>
              ) : null}
            </div>

            <div className="relative z-10 space-y-4">
              {spotlight && spotlightTone ? (
                <div className="card-elevated px-5 py-5">
                  <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.18em] text-slate-500">
                    <TriangleAlert className="h-3.5 w-3.5 text-rose-300" />
                    Spotlight
                  </div>
                  <h2 className="mt-3 text-lg font-semibold text-slate-100">
                    {spotlight.title}
                  </h2>
                  <div className="mt-4 flex flex-wrap gap-2">
                    <span
                      className={`rounded-full border px-3 py-1 text-[10px] uppercase tracking-[0.16em] ${spotlightTone.bg} ${spotlightTone.color} ${spotlightTone.border}`}
                    >
                      {spotlightTone.label}
                    </span>
                    <span className="rounded-full border border-slate-700/70 bg-slate-950/70 px-3 py-1 text-[10px] uppercase tracking-[0.16em] text-slate-300">
                      {spotlight.component_id}
                    </span>
                    <span className="rounded-full border border-amber-500/20 bg-amber-500/10 px-3 py-1 text-[10px] uppercase tracking-[0.16em] text-amber-300">
                      {spotlight.vote_count} votes
                    </span>
                  </div>
                  <p className="mt-4 text-sm leading-relaxed text-slate-300">
                    Highest-voted unresolved feedback item in the current
                    summary. Use the stream below to inspect context and
                    resolution state.
                  </p>
                </div>
              ) : (
                <div className="card-elevated px-5 py-5">
                  <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.18em] text-slate-500">
                    <Sparkles className="h-3.5 w-3.5 text-phosphor-300" />
                    Signal health
                  </div>
                  <p className="mt-3 text-sm leading-relaxed text-slate-300">
                    Feedback is flowing. Once a high-signal unresolved item
                    appears, it will surface here automatically.
                  </p>
                </div>
              )}
            </div>
          </div>
        </motion.section>

        {error && (
          <div className="rounded-[1.35rem] border border-rose-500/20 bg-rose-500/10 p-4 text-sm text-rose-300">
            Failed to load feedback data. Verify the backend is running.
          </div>
        )}

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

        <motion.section
          initial={{ opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{
            duration: 0.4,
            delay: 0.08,
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
          <FeedbackBoard
            items={itemsData?.items ?? []}
            total={itemsData?.total ?? 0}
            isLoading={itemsLoading}
            filters={filters}
            onFiltersChange={handleFiltersChange}
            onItemClick={setSelectedId}
            selectedId={selectedId}
          />
        </motion.section>
      </div>
    </div>
  )
}
