'use client'

import { Filter, Search } from 'lucide-react'
import type { StatusFilter } from './MockupStatsGrid'

export type TypeFilter =
  | 'all'
  | 'component'
  | 'page'
  | 'layout'
  | 'icon'
  | 'illustration'
  | 'sprite'
  | 'sheet'

interface DesignFiltersProps {
  searchQuery: string
  statusFilter: StatusFilter
  typeFilter: TypeFilter
  searchPlaceholder?: string
  onSearchChange: (query: string) => void
  onStatusFilterChange: (status: StatusFilter) => void
  onTypeFilterChange: (type: TypeFilter) => void
}

export function DesignFilters({
  searchQuery,
  statusFilter,
  typeFilter,
  searchPlaceholder = 'Search mockups...',
  onSearchChange,
  onStatusFilterChange,
  onTypeFilterChange,
}: DesignFiltersProps): React.ReactElement {
  return (
    <div className="flex flex-wrap items-center gap-4 mb-6">
      {/* Search */}
      <div className="relative flex-1 max-w-md">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
        <input
          type="text"
          placeholder={searchPlaceholder}
          value={searchQuery}
          onChange={(e) => onSearchChange(e.target.value)}
          className="w-full pl-10 pr-4 py-2 bg-slate-900/80 border border-slate-700 rounded-lg text-slate-100 placeholder-slate-500 focus-visible:outline-none focus-visible:border-phosphor-500/50 focus-visible:ring-1 focus-visible:ring-phosphor-500/20 transition-all"
        />
      </div>

      {/* Status filter */}
      <div className="flex items-center gap-2">
        <Filter className="w-4 h-4 text-slate-400" />
        <select
          value={statusFilter}
          onChange={(e) => onStatusFilterChange(e.target.value as StatusFilter)}
          aria-label="Filter by status"
          className="bg-slate-900/80 border border-slate-700 rounded-lg px-3 py-2 text-slate-100 focus-visible:outline-none focus-visible:border-phosphor-500/50 focus-visible:ring-1 focus-visible:ring-phosphor-500/20 transition-colors"
        >
          <option value="all">All Status</option>
          <option value="generated">Generated</option>
          <option value="pending_approval">Pending Approval</option>
          <option value="approved">Approved</option>
          <option value="rejected">Rejected</option>
          <option value="applied">Applied</option>
        </select>
      </div>

      {/* Type filter */}
      <select
        value={typeFilter}
        onChange={(e) => onTypeFilterChange(e.target.value as TypeFilter)}
        aria-label="Filter by type"
        className="bg-slate-900/80 border border-slate-700 rounded-lg px-3 py-2 text-slate-100 focus-visible:outline-none focus-visible:border-phosphor-500/50 focus-visible:ring-1 focus-visible:ring-phosphor-500/20 transition-colors"
      >
        <option value="all">All Types</option>
        <option value="component">Component</option>
        <option value="page">Page</option>
        <option value="layout">Layout</option>
        <option value="icon">Icon</option>
        <option value="illustration">Illustration</option>
        <option value="sprite">Sprite</option>
        <option value="sheet">Sprite Sheet</option>
      </select>
    </div>
  )
}
