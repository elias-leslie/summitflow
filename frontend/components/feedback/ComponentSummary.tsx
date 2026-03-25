'use client'

import { clsx } from 'clsx'
import { ChevronRight, Loader2 } from 'lucide-react'
import { useState } from 'react'
import type { ComponentBreakdown, FeedbackSummary } from '@/lib/api/feedback'
import { COMPONENT_GROUPS } from './feedbackConstants'

// ─── Constants ───────────────────────────────────────────────────

const COMPONENT_LABELS: Record<string, string> = {
  'sf.cli': 'ST CLI',
  'sf.cli.memory': 'Memory CLI',
  'sf.dt': 'Dev Tools',
  'sf.quality': 'Quality Gates',
  'sf.worktree': 'Worktree',
  'sf.api': 'SF API',
  'sf.search': 'Search',
  'sf.storage': 'Storage',
  'sf.workflows': 'Workflows',
  'sf.explorer': 'Explorer',
  'sf.frontend': 'Frontend',
  'sf.scripts': 'Scripts',
  'sf.hooks': 'Hooks',
  'ah.memory': 'Memory',
  'ah.memory.tiers': 'Memory Tiers',
  'ah.memory.continuity': 'Continuity',
  'ah.memory.citations': 'Citations',
  'ah.memory.learning': 'Learning',
  'ah.completion': 'Completion',
  'ah.adapters': 'Adapters',
  'ah.sessions': 'Sessions',
  'ah.sdk': 'SDK',
  'ah.orchestration': 'Orchestration',
  'ah.hooks': 'AH Hooks',
  'ah.codebase': 'Codebase',
  'xc.tool_registry': 'Tool Registry',
  'xc.error_handling': 'Error Handling',
  'xc.documentation': 'Documentation',
  'xc.testing': 'Testing',
  'coderabbit.suggestions': 'CodeRabbit',
}

const GROUP_TONE: Record<string, string> = {
  SummitFlow: 'border-cyan-500/15 bg-cyan-500/8',
  'Agent Hub': 'border-rose-500/15 bg-rose-500/8',
  'Cross-Cutting': 'border-amber-500/15 bg-amber-500/8',
}

// ─── Ratio Bar ───────────────────────────────────────────────────

function RatioBar({ data }: { data: ComponentBreakdown }) {
  const total = data.friction + data.idea + data.praise
  if (total === 0) return null
  return (
    <div className="flex h-2 w-20 shrink-0 overflow-hidden rounded-full bg-slate-800/50">
      {data.friction > 0 && (
        <div
          className="bg-red-500 transition-all duration-300"
          style={{ flex: data.friction }}
        />
      )}
      {data.idea > 0 && (
        <div
          className="bg-amber-500 transition-all duration-300"
          style={{ flex: data.idea }}
        />
      )}
      {data.praise > 0 && (
        <div
          className="bg-emerald-500 transition-all duration-300"
          style={{ flex: data.praise }}
        />
      )}
    </div>
  )
}

// ─── Component Row ───────────────────────────────────────────────

function ComponentRow({
  componentId,
  data,
  isActive,
  onClick,
}: {
  componentId: string
  data: ComponentBreakdown
  isActive: boolean
  onClick: () => void
}) {
  const label = COMPONENT_LABELS[componentId] || componentId

  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={isActive}
      className={clsx(
        'flex w-full items-center gap-3 rounded-[1.1rem] border px-3 py-3 text-left transition-all',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-phosphor-500/40',
        isActive
          ? 'border-phosphor-500/20 bg-slate-700/40 ring-1 ring-phosphor-500/20'
          : 'border-slate-800/70 bg-slate-950/40 hover:bg-slate-800/40',
      )}
    >
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm text-slate-200">{label}</div>
        <div className="mt-1 text-[10px] uppercase tracking-[0.16em] text-slate-500">
          {componentId}
        </div>
      </div>
      <div className="flex items-center gap-2">
        <RatioBar data={data} />
        {data.open > 0 && (
          <span className="rounded-full border border-rose-500/20 bg-rose-500/10 px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.16em] text-rose-300">
            {data.open} open
          </span>
        )}
        <span className="rounded-full border border-slate-700/70 bg-slate-950/70 px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.16em] text-slate-400">
          {data.total}
        </span>
      </div>
    </button>
  )
}

// ─── Group Section ───────────────────────────────────────────────

function GroupSection({
  groupName,
  components,
  byComponent,
  activeComponent,
  onComponentClick,
}: {
  groupName: string
  components: string[]
  byComponent: Record<string, ComponentBreakdown>
  activeComponent: string | undefined
  onComponentClick: (componentId: string | undefined) => void
}) {
  const [expanded, setExpanded] = useState(true)

  // Only show components that have feedback
  const withFeedback = components.filter((c) => byComponent[c]?.total > 0)

  // Also include any components in byComponent that match this group's prefix
  // but aren't in the static list
  const groupPrefixes =
    groupName === 'SummitFlow'
      ? ['sf.']
      : groupName === 'Agent Hub'
        ? ['ah.']
        : ['xc.']

  const extraComponents = Object.keys(byComponent).filter(
    (c) =>
      !components.includes(c) &&
      groupPrefixes.some((p) => c.startsWith(p)) &&
      byComponent[c].total > 0,
  )

  const allComponents = [...withFeedback, ...extraComponents]
  if (allComponents.length === 0) return null

  const groupTotal = allComponents.reduce(
    (sum, c) => sum + (byComponent[c]?.total ?? 0),
    0,
  )
  const groupOpen = allComponents.reduce(
    (sum, c) => sum + (byComponent[c]?.open ?? 0),
    0,
  )

  return (
    <div
      className={clsx(
        'overflow-hidden rounded-[1.5rem] border transition-all duration-200',
        GROUP_TONE[groupName] ?? 'border-slate-700/60 bg-slate-800/40',
        expanded ? 'border-slate-700/80' : 'hover:bg-slate-800/60',
      )}
    >
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        aria-expanded={expanded}
        className="flex w-full items-center gap-3 px-4 py-4 text-left transition-colors hover:bg-slate-800/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-phosphor-500/40"
      >
        <ChevronRight
          className={clsx(
            'h-3.5 w-3.5 shrink-0 text-slate-600 transition-transform duration-200',
            expanded && 'rotate-90',
          )}
        />
        <div className="min-w-0 flex-1">
          <div className="text-sm font-medium text-slate-200">{groupName}</div>
          <div className="mt-1 text-[10px] uppercase tracking-[0.16em] text-slate-500">
            {groupTotal} total signals
          </div>
        </div>
        <div className="flex items-center gap-2">
          {groupOpen > 0 && (
            <span className="rounded-full border border-rose-500/20 bg-rose-500/10 px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.16em] text-rose-300">
              {groupOpen} open
            </span>
          )}
          <span className="rounded-full border border-slate-700/70 bg-slate-950/70 px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.16em] text-slate-400">
            {groupTotal}
          </span>
        </div>
      </button>

      <div
        className={clsx(
          'grid transition-all duration-200 ease-out',
          expanded
            ? 'grid-rows-[1fr] opacity-100'
            : 'grid-rows-[0fr] opacity-0',
        )}
      >
        <div className="overflow-hidden">
          <div className="space-y-2 border-t border-slate-800/40 px-3 py-3">
            {allComponents.map((componentId) => (
              <ComponentRow
                key={componentId}
                componentId={componentId}
                data={byComponent[componentId]}
                isActive={activeComponent === componentId}
                onClick={() =>
                  onComponentClick(
                    activeComponent === componentId ? undefined : componentId,
                  )
                }
              />
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

// ─── Main ────────────────────────────────────────────────────────

interface ComponentSummaryProps {
  summary: FeedbackSummary | undefined
  isLoading: boolean
  activeComponent: string | undefined
  onComponentClick: (componentId: string | undefined) => void
}

export function ComponentSummary({
  summary,
  isLoading,
  activeComponent,
  onComponentClick,
}: ComponentSummaryProps) {
  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="w-5 h-5 animate-spin text-slate-500" />
      </div>
    )
  }

  if (!summary || !summary.by_component) return null

  const hasAny = Object.values(summary.by_component).some((d) => d.total > 0)
  if (!hasAny) return null

  return (
    <section className="card-elevated space-y-4 px-5 py-5">
      <div>
        <div className="eyebrow">Components</div>
        <h2 className="display mt-2 text-2xl font-semibold text-slate-100">
          Components
        </h2>
        <p className="mt-2 text-sm text-slate-400">
          Compare where SummitFlow, Agent Hub, and cross-cutting tooling are
          collecting the most signal.
        </p>
      </div>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        {Object.entries(COMPONENT_GROUPS).map(([groupName, components]) => (
          <GroupSection
            key={groupName}
            groupName={groupName}
            components={components}
            byComponent={summary.by_component}
            activeComponent={activeComponent}
            onComponentClick={onComponentClick}
          />
        ))}
      </div>
    </section>
  )
}
