import { Lightbulb, Sparkles, TrendingUp, Zap } from 'lucide-react'

// ============================================================================
// Type configuration
// ============================================================================

export const TYPE_CONFIG = {
  friction: {
    icon: Zap,
    label: 'Friction',
    color: 'text-rose-400',
    bg: 'bg-rose-500/10',
    border: 'border-rose-500/30',
  },
  idea: {
    icon: Lightbulb,
    label: 'Idea',
    color: 'text-amber-400',
    bg: 'bg-amber-500/10',
    border: 'border-amber-500/30',
  },
  improvement: {
    icon: TrendingUp,
    label: 'Improvement',
    color: 'text-blue-400',
    bg: 'bg-blue-500/10',
    border: 'border-blue-500/30',
  },
  praise: {
    icon: Sparkles,
    label: 'Praise',
    color: 'text-emerald-400',
    bg: 'bg-emerald-500/10',
    border: 'border-emerald-500/30',
  },
} as const

// ============================================================================
// Status configuration
// ============================================================================

export const STATUS_CONFIG = {
  active: {
    label: 'Active',
    color: 'text-sky-300',
    bg: 'bg-sky-500/10',
    border: 'border-sky-500/30',
  },
  open: {
    label: 'Open',
    color: 'text-slate-300',
    bg: 'bg-slate-600/30',
    border: 'border-slate-500/30',
  },
  acknowledged: {
    label: 'Ack',
    color: 'text-amber-400',
    bg: 'bg-amber-500/10',
    border: 'border-amber-500/30',
  },
  resolved: {
    label: 'Resolved',
    color: 'text-emerald-400',
    bg: 'bg-emerald-500/10',
    border: 'border-emerald-500/30',
  },
  wont_fix: {
    label: "Won't Fix",
    color: 'text-slate-500',
    bg: 'bg-slate-700/30',
    border: 'border-slate-600/30',
  },
  archived: {
    label: 'Archived',
    color: 'text-slate-500',
    bg: 'bg-slate-800/50',
    border: 'border-slate-700/40',
  },
} as const

// ============================================================================
// Sort options
// ============================================================================

export const SORT_OPTIONS = [
  { value: 'votes', label: 'Most Voted' },
  { value: 'newest', label: 'Newest' },
  { value: 'oldest', label: 'Oldest' },
] as const

// ============================================================================
// Component groups
// ============================================================================

export const COMPONENT_GROUPS: Record<string, string[]> = {
  SummitFlow: [
    'sf.cli',
    'sf.cli.memory',
    'sf.dt',
    'sf.quality',
    'sf.checkpoints',
    'sf.api',
    'sf.search',
    'sf.storage',
    'sf.workflows',
    'sf.explorer',
    'sf.frontend',
    'sf.scripts',
  ],
  'Agent Hub': [
    'ah.memory',
    'ah.memory.tiers',
    'ah.memory.continuity',
    'ah.memory.citations',
    'ah.memory.learning',
    'ah.completion',
    'ah.adapters',
    'ah.sessions',
    'ah.sdk',
    'ah.orchestration',
    'ah.hooks',
  ],
  'Cross-Cutting': [
    'xc.tool_registry',
    'xc.error_handling',
    'xc.documentation',
    'xc.testing',
  ],
}
