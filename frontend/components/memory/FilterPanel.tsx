'use client'

import { clsx } from 'clsx'
import { Filter, X } from 'lucide-react'

// Observation types matching backend taxonomy
const OBSERVATION_TYPES = [
  { value: 'all', label: 'All Types' },
  { value: 'pattern', label: 'Pattern' },
  { value: 'decision', label: 'Decision' },
  { value: 'error', label: 'Error' },
  { value: 'constraint', label: 'Constraint' },
  { value: 'architecture', label: 'Architecture' },
  { value: 'user_preference', label: 'User Preference' },
  { value: 'refactoring', label: 'Refactoring' },
]

// Concept tags matching backend taxonomy
const CONCEPT_TAGS = [
  {
    value: 'debugging',
    label: 'Debugging',
    color: 'bg-red-500/20 text-red-300',
  },
  {
    value: 'code_patterns',
    label: 'Code Patterns',
    color: 'bg-blue-500/20 text-blue-300',
  },
  {
    value: 'dependencies',
    label: 'Dependencies',
    color: 'bg-purple-500/20 text-purple-300',
  },
  {
    value: 'security',
    label: 'Security',
    color: 'bg-amber-500/20 text-amber-300',
  },
  {
    value: 'performance',
    label: 'Performance',
    color: 'bg-green-500/20 text-green-300',
  },
  { value: 'testing', label: 'Testing', color: 'bg-cyan-500/20 text-cyan-300' },
  {
    value: 'configuration',
    label: 'Configuration',
    color: 'bg-slate-500/20 text-slate-300',
  },
]

export interface SearchFilters {
  type: string
  concepts: string[]
  useSemantic: boolean
}

interface FilterPanelProps {
  filters: SearchFilters
  onChange: (filters: SearchFilters) => void
}

export function FilterPanel({ filters, onChange }: FilterPanelProps) {
  const toggleConcept = (concept: string) => {
    const newConcepts = filters.concepts.includes(concept)
      ? filters.concepts.filter((c) => c !== concept)
      : [...filters.concepts, concept]
    onChange({ ...filters, concepts: newConcepts })
  }

  const clearFilters = () => {
    onChange({ type: 'all', concepts: [], useSemantic: false })
  }

  const hasActiveFilters =
    filters.type !== 'all' || filters.concepts.length > 0 || filters.useSemantic

  return (
    <div className="space-y-4">
      {/* Type and Semantic Toggle Row */}
      <div className="flex items-center gap-4 flex-wrap">
        <div className="flex items-center gap-2">
          <Filter className="w-4 h-4 text-slate-500" />
          <select
            value={filters.type}
            onChange={(e) => onChange({ ...filters, type: e.target.value })}
            className={clsx(
              'px-3 py-1.5 rounded-lg text-sm',
              'bg-slate-800/50 border border-slate-700/50',
              'text-slate-200',
              'focus:outline-none focus:ring-2 focus:ring-blue-500/50',
              'cursor-pointer',
            )}
          >
            {OBSERVATION_TYPES.map((type) => (
              <option key={type.value} value={type.value}>
                {type.label}
              </option>
            ))}
          </select>
        </div>

        {/* Semantic Search Toggle */}
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={filters.useSemantic}
            onChange={(e) =>
              onChange({ ...filters, useSemantic: e.target.checked })
            }
            className="w-4 h-4 rounded bg-slate-700 border-slate-600 text-blue-600 focus:ring-blue-500/50"
          />
          <span className="text-sm text-slate-400">Semantic Search</span>
        </label>

        {hasActiveFilters && (
          <button
            onClick={clearFilters}
            className="flex items-center gap-1 px-2 py-1 text-xs text-slate-400 hover:text-slate-200 transition-colors"
          >
            <X className="w-3 h-3" />
            Clear Filters
          </button>
        )}
      </div>

      {/* Concept Tags */}
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-xs text-slate-500 uppercase tracking-wider">
          Concepts:
        </span>
        {CONCEPT_TAGS.map((concept) => (
          <button
            key={concept.value}
            onClick={() => toggleConcept(concept.value)}
            className={clsx(
              'px-2.5 py-1 rounded-full text-xs font-medium transition-all duration-200',
              filters.concepts.includes(concept.value)
                ? concept.color
                : 'bg-slate-700/50 text-slate-400 hover:bg-slate-700',
            )}
          >
            {concept.label}
          </button>
        ))}
      </div>
    </div>
  )
}
