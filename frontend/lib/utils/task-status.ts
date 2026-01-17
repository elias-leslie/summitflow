/**
 * Shared task status, phase, and priority utilities.
 * Consolidates duplicate definitions from TaskPreview, SubtasksSection, IssueTasksTab.
 */

import type { LucideIcon } from 'lucide-react'
import {
  CheckCircle2,
  Circle,
  Clock,
  Database,
  FileCode,
  Layout,
  PlayCircle,
  Search,
  Server,
  TestTube,
  XCircle,
} from 'lucide-react'

// =============================================================================
// Phase Configuration
// =============================================================================

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

/** Shorthand for just the phase icon */
export const PHASE_ICONS: Record<string, LucideIcon> = Object.fromEntries(
  Object.entries(PHASE_CONFIG).map(([k, v]) => [k, v.icon]),
)

/** Shorthand for "text-X bg-X/10" combined */
export const PHASE_COLORS: Record<string, string> = Object.fromEntries(
  Object.entries(PHASE_CONFIG).map(([k, v]) => [k, `${v.color} ${v.bgColor}`]),
)

// =============================================================================
// Task Status Configuration
// =============================================================================

export interface StatusConfig {
  icon: LucideIcon
  color: string
  label: string
}

export const STATUS_CONFIG: Record<string, StatusConfig> = {
  pending: {
    icon: Circle,
    color: 'text-slate-400',
    label: 'Pending',
  },
  running: {
    icon: PlayCircle,
    color: 'text-blue-400',
    label: 'Running',
  },
  completed: {
    icon: CheckCircle2,
    color: 'text-phosphor-400',
    label: 'Completed',
  },
  failed: {
    icon: XCircle,
    color: 'text-red-400',
    label: 'Failed',
  },
  cancelled: {
    icon: XCircle,
    color: 'text-slate-500',
    label: 'Cancelled',
  },
  blocked: {
    icon: Clock,
    color: 'text-amber-400',
    label: 'Blocked',
  },
}

// =============================================================================
// Priority Configuration
// =============================================================================

export interface PriorityConfig {
  label: string
  shortLabel: string
  color: string
}

export const PRIORITY_CONFIG: Record<number, PriorityConfig> = {
  0: { label: 'P0 Critical', shortLabel: 'P0', color: 'text-red-400' },
  1: { label: 'P1 High', shortLabel: 'P1', color: 'text-orange-400' },
  2: { label: 'P2 Medium', shortLabel: 'P2', color: 'text-yellow-400' },
  3: { label: 'P3 Low', shortLabel: 'P3', color: 'text-slate-400' },
  4: { label: 'P4 Backlog', shortLabel: 'P4', color: 'text-slate-500' },
}

// =============================================================================
// Category Configuration (for criteria)
// =============================================================================

export const CATEGORY_COLORS: Record<string, string> = {
  performance: 'text-amber-400 bg-amber-500/10 border-amber-500/20',
  correctness: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20',
  security: 'text-red-400 bg-red-500/10 border-red-500/20',
  quality: 'text-blue-400 bg-blue-500/10 border-blue-500/20',
}

// =============================================================================
// Helper Functions
// =============================================================================

export function getPhaseConfig(phase: string): PhaseConfig {
  return PHASE_CONFIG[phase] || PHASE_CONFIG.other
}

export function getStatusConfig(status: string): StatusConfig {
  return STATUS_CONFIG[status] || STATUS_CONFIG.pending
}

export function getPriorityConfig(priority: number): PriorityConfig {
  return PRIORITY_CONFIG[priority] || PRIORITY_CONFIG[2]
}

export function getCategoryColor(category: string): string {
  return (
    CATEGORY_COLORS[category] ||
    'text-slate-400 bg-slate-500/10 border-slate-500/20'
  )
}
