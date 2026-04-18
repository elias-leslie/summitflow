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
  'sf.checkpoints': 'Checkpoints',
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

// ─── Ratio Bar ───────────────────────────────────────────────────

function RatioBar({ data }: { data: ComponentBreakdown }) {
  const total = data.friction + data.idea + data.praise
  if (total === 0) return null
  return (
    <div className="flex gap-px h-1.5 rounded-full overflow-hidden bg-slate-800/50 w-16 shrink-0">
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
        'flex items-center gap-3 px-3 py-2 rounded-md text-left transition-all w-full',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-phosphor-500/40',
        isActive
          ? 'bg-slate-700/40 ring-1 ring-phosphor-500/20'
          : 'hover:bg-slate-800/40',
      )}
    >
      <span className="text-xs text-slate-300 truncate flex-1 min-w-0">
        {label}
      </span>
      <RatioBar data={data} />
      {data.open > 0 && (
        <span className="text-[10px] font-mono text-red-400 tabular-nums shrink-0">
          {data.open}
        </span>
      )}
      <span className="text-[10px] font-mono text-slate-600 tabular-nums shrink-0">
        {data.total}
      </span>
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
        'rounded-lg border border-slate-700/60 bg-slate-800/40 overflow-hidden transition-all duration-200',
        expanded ? 'border-slate-700/80' : 'hover:bg-slate-800/60',
      )}
    >
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        aria-expanded={expanded}
        className="flex w-full items-center gap-3 px-4 py-2.5 text-left transition-colors hover:bg-slate-800/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-phosphor-500/40"
      >
        <ChevronRight
          className={clsx(
            'w-3.5 h-3.5 text-slate-600 transition-transform duration-200 shrink-0',
            expanded && 'rotate-90',
          )}
        />
        <span className="text-xs font-medium text-slate-300">{groupName}</span>
        <span className="text-[10px] font-mono text-slate-600 tabular-nums">
          {groupTotal}
        </span>
        {groupOpen > 0 && (
          <span className="text-[10px] font-mono text-red-400 tabular-nums">
            {groupOpen} open
          </span>
        )}
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
          <div className="border-t border-slate-800/40 px-2 py-1.5 space-y-0.5">
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
    <section className="space-y-3">
      <div>
        <h2 className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-300 display">
          Components
        </h2>
        <p className="mt-1 text-xs text-slate-500">
          Feedback by system component
        </p>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
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
