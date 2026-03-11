'use client'

import {
  AlertCircle,
  Brain,
  Database,
  MessageSquare,
  Search,
  Terminal,
  X,
} from 'lucide-react'
import type { AgentEventType } from '@/lib/api/tasks'

interface FilterChip {
  id: AgentEventType | 'all' | 'messages' | 'tools' | 'memory'
  label: string
  icon: React.ReactNode
  eventTypes?: AgentEventType[]
}

const FILTER_CHIPS: FilterChip[] = [
  {
    id: 'all',
    label: 'All',
    icon: null,
    eventTypes: undefined,
  },
  {
    id: 'messages',
    label: 'Messages',
    icon: <MessageSquare className="h-3 w-3" />,
    eventTypes: ['user_message', 'assistant_message', 'system_message'],
  },
  {
    id: 'thinking',
    label: 'Thinking',
    icon: <Brain className="h-3 w-3" />,
    eventTypes: ['thinking'],
  },
  {
    id: 'tools',
    label: 'Tools',
    icon: <Terminal className="h-3 w-3" />,
    eventTypes: ['tool_use', 'tool_result'],
  },
  {
    id: 'memory',
    label: 'Memory',
    icon: <Database className="h-3 w-3" />,
    eventTypes: ['memory_inject', 'memory_cite'],
  },
  {
    id: 'error',
    label: 'Errors',
    icon: <AlertCircle className="h-3 w-3" />,
    eventTypes: ['error'],
  },
]

interface TimelineFiltersProps {
  activeFilter: string
  searchTerm: string
  onFilterChange: (filterId: string, eventTypes: AgentEventType[] | undefined) => void
  onSearchChange: (term: string) => void
  eventCounts?: Record<string, number>
}

export function TimelineFilters({
  activeFilter,
  searchTerm,
  onFilterChange,
  onSearchChange,
  eventCounts,
}: TimelineFiltersProps) {
  return (
    <div className="flex flex-col gap-2 px-3 py-2.5 bg-slate-900/80 border-b border-slate-800/50">
      <div className="flex items-center gap-1.5 flex-wrap">
        {FILTER_CHIPS.map((chip) => {
          const isActive = activeFilter === chip.id
          const count = chip.eventTypes
            ? chip.eventTypes.reduce((acc, et) => acc + (eventCounts?.[et] || 0), 0)
            : eventCounts
              ? Object.values(eventCounts).reduce((a, b) => a + b, 0)
              : 0

          return (
            <button
              key={chip.id}
              onClick={() => onFilterChange(chip.id, chip.eventTypes)}
              className={`
                flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium transition-all
                ${
                  isActive
                    ? 'bg-cyan-500/20 text-cyan-400 border border-cyan-500/40'
                    : 'bg-slate-800/50 text-slate-400 border border-slate-700/50 hover:bg-slate-700/50 hover:text-slate-300'
                }
              `}
            >
              {chip.icon}
              <span>{chip.label}</span>
              {count > 0 && (
                <span
                  className={`text-2xs px-1 py-0.5 rounded ${isActive ? 'bg-cyan-500/30' : 'bg-slate-700/70'}`}
                >
                  {count}
                </span>
              )}
            </button>
          )
        })}
      </div>

      <div className="relative">
        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-slate-500" />
        <input
          type="text"
          value={searchTerm}
          onChange={(e) => onSearchChange(e.target.value)}
          placeholder="Search events..."
          className="w-full pl-8 pr-8 py-1.5 text-sm bg-slate-800/50 border border-slate-700/50 rounded-md text-slate-300 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-cyan-500/50 focus:border-cyan-500/50"
        />
        {searchTerm && (
          <button
            onClick={() => onSearchChange('')}
            aria-label="Clear search"
            className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        )}
      </div>
    </div>
  )
}

export { FILTER_CHIPS }
export type { FilterChip }
