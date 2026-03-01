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
  onSearchChange: (query: string) => void
  onStatusFilterChange: (status: StatusFilter) => void
  onTypeFilterChange: (type: TypeFilter) => void
}

export function DesignFilters({
  searchQuery,
  statusFilter,
  typeFilter,
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
          placeholder="Search mockups..."
          value={searchQuery}
          onChange={(e) => onSearchChange(e.target.value)}
          className="w-full pl-10 pr-4 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-outrun-500"
        />
      </div>

      {/* Status filter */}
      <div className="flex items-center gap-2">
        <Filter className="w-4 h-4 text-slate-400" />
        <select
          value={statusFilter}
          onChange={(e) => onStatusFilterChange(e.target.value as StatusFilter)}
          className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white focus:outline-none focus:ring-2 focus:ring-outrun-500"
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
        className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white focus:outline-none focus:ring-2 focus:ring-outrun-500"
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
