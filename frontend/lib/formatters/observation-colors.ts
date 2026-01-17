/**
 * Color mappings and type utilities for observation display.
 */

import { Brain, Clock, Database, Layers, type LucideIcon } from 'lucide-react'

// Observation types from the memory system
export type ObservationType =
  | 'bugfix'
  | 'feature'
  | 'refactor'
  | 'change'
  | 'discovery'
  | 'decision'

// Concept types from the memory system
export type ConceptType =
  | 'how-it-works'
  | 'why-it-exists'
  | 'what-changed'
  | 'problem-solution'
  | 'gotcha'
  | 'pattern'
  | 'trade-off'

// Color mapping for observation types
export const OBSERVATION_TYPE_COLORS: Record<ObservationType, string> = {
  bugfix: 'bg-red-500/10 text-red-500 border-red-500/20',
  feature: 'bg-emerald-500/10 text-emerald-500 border-emerald-500/20',
  refactor: 'bg-blue-500/10 text-blue-500 border-blue-500/20',
  change: 'bg-amber-500/10 text-amber-500 border-amber-500/20',
  discovery: 'bg-purple-500/10 text-purple-500 border-purple-500/20',
  decision: 'bg-cyan-500/10 text-cyan-500 border-cyan-500/20',
}

// Color mapping for concepts
export const CONCEPT_COLORS: Record<ConceptType, string> = {
  'how-it-works': 'bg-slate-500/10 text-slate-500',
  'why-it-exists': 'bg-indigo-500/10 text-indigo-400',
  'what-changed': 'bg-amber-500/10 text-amber-400',
  'problem-solution': 'bg-emerald-500/10 text-emerald-400',
  gotcha: 'bg-red-500/10 text-red-400',
  pattern: 'bg-blue-500/10 text-blue-400',
  'trade-off': 'bg-purple-500/10 text-purple-400',
}

// All observation types for filtering
export const OBSERVATION_TYPES: ObservationType[] = [
  'bugfix',
  'feature',
  'refactor',
  'change',
  'discovery',
  'decision',
]

// All concept types for filtering
export const CONCEPT_TYPES: ConceptType[] = [
  'how-it-works',
  'why-it-exists',
  'what-changed',
  'problem-solution',
  'gotcha',
  'pattern',
  'trade-off',
]

// Context item type icons
export const CONTEXT_TYPE_ICONS: Record<string, LucideIcon> = {
  observation: Brain,
  checkpoint: Clock,
  pattern: Layers,
  default: Database,
}

// Color mapping for context item types
export const CONTEXT_TYPE_COLORS: Record<string, string> = {
  observation: 'bg-purple-500/10 text-purple-500 border-purple-500/20',
  checkpoint: 'bg-amber-500/10 text-amber-500 border-amber-500/20',
  pattern: 'bg-blue-500/10 text-blue-500 border-blue-500/20',
  default: 'bg-slate-500/10 text-slate-500 border-slate-500/20',
}

/**
 * Get icon component for a context item type.
 */
export function getContextTypeIcon(type: string): LucideIcon {
  return CONTEXT_TYPE_ICONS[type] || CONTEXT_TYPE_ICONS.default
}

/**
 * Get color classes for a context item type.
 */
export function getContextTypeColor(type: string): string {
  return CONTEXT_TYPE_COLORS[type] || CONTEXT_TYPE_COLORS.default
}
