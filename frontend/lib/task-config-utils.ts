/**
 * Phase and category configuration for task subtask display.
 */

import type { LucideIcon } from 'lucide-react'
import {
  Database,
  FileCode,
  Layout,
  Search,
  Server,
  TestTube,
} from 'lucide-react'

// ============================================================================
// Phase Configuration (subtask phases)
// ============================================================================

export interface PhaseConfig {
  icon: LucideIcon
  color: string
  bgColor: string
}

export const PHASE_CONFIG: Record<string, PhaseConfig> = {
  research: {
    icon: Search,
    color: 'text-blue-400',
    bgColor: 'bg-blue-500/10',
  },
  database: {
    icon: Database,
    color: 'text-amber-400',
    bgColor: 'bg-amber-500/10',
  },
  backend: {
    icon: Server,
    color: 'text-emerald-400',
    bgColor: 'bg-emerald-500/10',
  },
  frontend: {
    icon: Layout,
    color: 'text-violet-400',
    bgColor: 'bg-violet-500/10',
  },
  testing: {
    icon: TestTube,
    color: 'text-rose-400',
    bgColor: 'bg-rose-500/10',
  },
  other: {
    icon: FileCode,
    color: 'text-slate-400',
    bgColor: 'bg-slate-500/10',
  },
}

export const PHASE_ICONS: Record<string, LucideIcon> = Object.fromEntries(
  Object.entries(PHASE_CONFIG).map(([k, v]) => [k, v.icon]),
)

export const PHASE_COLORS: Record<string, string> = Object.fromEntries(
  Object.entries(PHASE_CONFIG).map(([k, v]) => [k, `${v.color} ${v.bgColor}`]),
)

export function getPhaseConfig(phase: string): PhaseConfig {
  return PHASE_CONFIG[phase] || PHASE_CONFIG.other
}

// ============================================================================
// Category Colors (for acceptance criteria)
// ============================================================================

export const CATEGORY_COLORS: Record<string, string> = {
  performance: 'text-amber-400 bg-amber-500/10 border-amber-500/20',
  correctness: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20',
  security: 'text-red-400 bg-red-500/10 border-red-500/20',
  quality: 'text-blue-400 bg-blue-500/10 border-blue-500/20',
}

export function getCategoryColor(category: string): string {
  return (
    CATEGORY_COLORS[category] ||
    'text-slate-400 bg-slate-500/10 border-slate-500/20'
  )
}
