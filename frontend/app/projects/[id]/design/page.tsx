'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Box,
  CheckCircle2,
  CheckSquare,
  Clock,
  Filter,
  Grid3X3,
  Image as ImageIcon,
  List,
  Loader2,
  Palette,
  Search,
  Sparkles,
  Trash2,
  X,
  XCircle,
} from 'lucide-react'
import { useParams } from 'next/navigation'
import { useState } from 'react'
import { GenerateMockupDialog } from '@/components/design/GenerateMockupDialog'
import { MockupCard } from '@/components/design/MockupCard'
import { MockupDetailModal } from '@/components/design/MockupDetailModal'
import { DesignStandardsPanel } from '@/components/explorer/DesignStandardsPanel'
import {
  deleteMockup,
  fetchMockupStats,
  fetchMockups,
  type Mockup,
} from '@/lib/api/mockups'

type ViewMode = 'grid' | 'list'
type StatusFilter =
  | 'all'
  | 'generated'
  | 'pending_approval'
  | 'approved'
  | 'rejected'
  | 'applied'
type TypeFilter =
  | 'all'
  | 'component'
  | 'page'
  | 'layout'
  | 'icon'
  | 'illustration'

export default function DesignPage() {
  const params = useParams()
  const projectId = params.id as string

  // View and filter state
  const [viewMode, setViewMode] = useState<ViewMode>('grid')
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')
  const [typeFilter, setTypeFilter] = useState<TypeFilter>('all')
  const [searchQuery, setSearchQuery] = useState('')
  const [page, setPage] = useState(0)
  const pageSize = 24

  // Modal state
  const [selectedMockup, setSelectedMockup] = useState<Mockup | null>(null)
  const [modalOpen, setModalOpen] = useState(false)
  const [generateDialogOpen, setGenerateDialogOpen] = useState(false)

  // Multi-select delete state
  const [selectMode, setSelectMode] = useState(false)
  const [selectedMockups, setSelectedMockups] = useState<Set<string>>(new Set())
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)

  const queryClient = useQueryClient()

  // Fetch mockups
  const {
    data: mockupsData,
    isLoading,
    error,
    refetch,
  } = useQuery({
    queryKey: [
      'mockups',
      projectId,
      statusFilter,
      typeFilter,
      searchQuery,
      page,
    ],
    queryFn: () =>
      fetchMockups(projectId, {
        limit: pageSize,
        offset: page * pageSize,
        status: statusFilter === 'all' ? undefined : statusFilter,
        mockup_type: typeFilter === 'all' ? undefined : typeFilter,
        search: searchQuery || undefined,
      }),
  })

  // Fetch stats
  const { data: stats } = useQuery({
    queryKey: ['mockup-stats', projectId],
    queryFn: () => fetchMockupStats(projectId),
  })

  const mockups = mockupsData?.items ?? []
  const totalCount = mockupsData?.total ?? 0

  // Delete mutation
  const deleteMutation = useMutation({
    mutationFn: async (mockupIds: string[]) => {
      await Promise.all(mockupIds.map((id) => deleteMockup(projectId, id)))
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['mockups', projectId] })
      queryClient.invalidateQueries({ queryKey: ['mockup-stats', projectId] })
      setSelectedMockups(new Set())
      setSelectMode(false)
      setShowDeleteConfirm(false)
    },
  })

  const handleMockupClick = (mockup: Mockup) => {
    if (selectMode) {
      toggleMockupSelection(mockup.mockup_id)
    } else {
      setSelectedMockup(mockup)
      setModalOpen(true)
    }
  }

  const toggleMockupSelection = (mockupId: string) => {
    setSelectedMockups((prev) => {
      const newSet = new Set(prev)
      if (newSet.has(mockupId)) {
        newSet.delete(mockupId)
      } else {
        newSet.add(mockupId)
      }
      return newSet
    })
  }

  const handleBulkDelete = () => {
    if (selectedMockups.size === 0) return
    setShowDeleteConfirm(true)
  }

  const confirmDelete = () => {
    deleteMutation.mutate(Array.from(selectedMockups))
  }

  const cancelSelectMode = () => {
    setSelectMode(false)
    setSelectedMockups(new Set())
  }

  const statusIcons: Record<string, React.ReactNode> = {
    generated: <Sparkles className="w-4 h-4 text-blue-400" />,
    pending_approval: <Clock className="w-4 h-4 text-amber-400" />,
    approved: <CheckCircle2 className="w-4 h-4 text-emerald-400" />,
    rejected: <XCircle className="w-4 h-4 text-rose-400" />,
    applied: <Box className="w-4 h-4 text-purple-400" />,
  }

  return (
    <div className="h-full flex gap-4 p-4">
      {/* Main content */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            <Palette className="w-6 h-6 text-outrun-500" />
            <h1 className="display text-xl font-semibold text-white">Design</h1>
            {stats && (
              <span className="text-slate-400 text-sm">
                {stats.total} mockups
              </span>
            )}
          </div>

          {/* Actions */}
          <div className="flex items-center gap-4">
            {/* Generate button */}
            {!selectMode && (
              <button
                onClick={() => setGenerateDialogOpen(true)}
                className="btn-primary flex items-center gap-2"
              >
                <Sparkles className="w-4 h-4" />
                Generate Mockup
              </button>
            )}

            {/* Select mode toggle */}
            {mockups.length > 0 && (
              <button
                onClick={() =>
                  selectMode ? cancelSelectMode() : setSelectMode(true)
                }
                className={`flex items-center gap-2 px-3 py-2 rounded-lg transition-all ${
                  selectMode
                    ? 'bg-outrun-500/20 text-outrun-400 border border-outrun-500/50'
                    : 'bg-slate-800 text-slate-300 hover:text-white border border-slate-700'
                }`}
              >
                {selectMode ? (
                  <X className="w-4 h-4" />
                ) : (
                  <CheckSquare className="w-4 h-4" />
                )}
                {selectMode ? 'Cancel' : 'Select'}
              </button>
            )}

            {/* View toggle */}
            {!selectMode && (
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setViewMode('grid')}
                  className={`p-2 rounded ${
                    viewMode === 'grid'
                      ? 'bg-outrun-500/20 text-outrun-400'
                      : 'text-slate-400 hover:text-white'
                  }`}
                >
                  <Grid3X3 className="w-4 h-4" />
                </button>
                <button
                  onClick={() => setViewMode('list')}
                  className={`p-2 rounded ${
                    viewMode === 'list'
                      ? 'bg-outrun-500/20 text-outrun-400'
                      : 'text-slate-400 hover:text-white'
                  }`}
                >
                  <List className="w-4 h-4" />
                </button>
              </div>
            )}
          </div>
        </div>

        {/* Stats summary */}
        {stats && (
          <div className="grid grid-cols-5 gap-4 mb-6">
            {Object.entries(stats.by_status).map(([status, count]) => (
              <div
                key={status}
                className="card p-3 flex items-center gap-3 cursor-pointer hover:bg-slate-700/50"
                onClick={() => setStatusFilter(status as StatusFilter)}
              >
                {statusIcons[status]}
                <div>
                  <div className="text-white font-medium">{count}</div>
                  <div className="text-slate-400 text-xs capitalize">
                    {status.replace('_', ' ')}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Filters */}
        <div className="flex flex-wrap items-center gap-4 mb-6">
          {/* Search */}
          <div className="relative flex-1 max-w-md">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
            <input
              type="text"
              placeholder="Search mockups..."
              value={searchQuery}
              onChange={(e) => {
                setSearchQuery(e.target.value)
                setPage(0)
              }}
              className="w-full pl-10 pr-4 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-outrun-500"
            />
          </div>

          {/* Status filter */}
          <div className="flex items-center gap-2">
            <Filter className="w-4 h-4 text-slate-400" />
            <select
              value={statusFilter}
              onChange={(e) => {
                setStatusFilter(e.target.value as StatusFilter)
                setPage(0)
              }}
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
            onChange={(e) => {
              setTypeFilter(e.target.value as TypeFilter)
              setPage(0)
            }}
            className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white focus:outline-none focus:ring-2 focus:ring-outrun-500"
          >
            <option value="all">All Types</option>
            <option value="component">Component</option>
            <option value="page">Page</option>
            <option value="layout">Layout</option>
            <option value="icon">Icon</option>
            <option value="illustration">Illustration</option>
          </select>
        </div>

        {/* Bulk action bar */}
        {selectMode && selectedMockups.size > 0 && (
          <div className="fixed bottom-8 left-1/2 -translate-x-1/2 z-40 animate-in slide-in-from-bottom-4">
            <div className="bg-slate-900 border-2 border-outrun-500/50 rounded-xl px-6 py-4 shadow-2xl shadow-outrun-500/20 flex items-center gap-4">
              <div className="flex items-center gap-2">
                <CheckSquare className="w-5 h-5 text-outrun-400" />
                <span className="text-white font-medium">
                  {selectedMockups.size} selected
                </span>
              </div>
              <div className="h-6 w-px bg-slate-700" />
              <button
                onClick={handleBulkDelete}
                disabled={deleteMutation.isPending}
                className="flex items-center gap-2 px-4 py-2 bg-rose-500/10 hover:bg-rose-500/20 text-rose-400 rounded-lg transition-all border border-rose-500/30 hover:border-rose-500/50 disabled:opacity-50"
              >
                {deleteMutation.isPending ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Trash2 className="w-4 h-4" />
                )}
                Delete {selectedMockups.size > 1 ? 'All' : ''}
              </button>
            </div>
          </div>
        )}

        {/* Loading state */}
        {isLoading && (
          <div className="flex-1 flex items-center justify-center">
            <Loader2 className="w-8 h-8 text-outrun-500 animate-spin" />
          </div>
        )}

        {/* Error state */}
        {error && (
          <div className="flex-1 flex items-center justify-center">
            <div className="card p-8 text-center max-w-md">
              <XCircle className="w-10 h-10 text-rose-500 mx-auto mb-4" />
              <p className="text-white mb-2">Failed to load mockups</p>
              <p className="text-slate-400 text-sm mb-4">
                {error instanceof Error ? error.message : 'Unknown error'}
              </p>
              <button onClick={() => refetch()} className="btn-primary">
                Retry
              </button>
            </div>
          </div>
        )}

        {/* Empty state */}
        {!isLoading && !error && mockups.length === 0 && (
          <div className="flex-1 flex items-center justify-center">
            <div className="card p-8 text-center max-w-md">
              <ImageIcon className="w-10 h-10 text-slate-500 mx-auto mb-4" />
              <h2 className="text-white font-medium mb-2">No mockups yet</h2>
              <p className="text-slate-400 text-sm">
                Design mockups will appear here when generated by /polish_it or
                the design workflow.
              </p>
            </div>
          </div>
        )}

        {/* Mockups grid/list */}
        {!isLoading && !error && mockups.length > 0 && (
          <div className="flex-1 overflow-auto">
            <div
              className={
                viewMode === 'grid'
                  ? 'grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4'
                  : 'flex flex-col gap-2'
              }
            >
              {mockups.map((mockup) => (
                <MockupCard
                  key={mockup.mockup_id}
                  mockup={mockup}
                  viewMode={viewMode}
                  onClick={() => handleMockupClick(mockup)}
                  selectMode={selectMode}
                  isSelected={selectedMockups.has(mockup.mockup_id)}
                />
              ))}
            </div>

            {/* Pagination */}
            {totalCount > pageSize && (
              <div className="flex items-center justify-center gap-4 mt-6 pb-4">
                <button
                  onClick={() => setPage((p) => Math.max(0, p - 1))}
                  disabled={page === 0}
                  className="btn-secondary disabled:opacity-50"
                >
                  Previous
                </button>
                <span className="text-slate-400">
                  Page {page + 1} of {Math.ceil(totalCount / pageSize)}
                </span>
                <button
                  onClick={() => setPage((p) => p + 1)}
                  disabled={(page + 1) * pageSize >= totalCount}
                  className="btn-secondary disabled:opacity-50"
                >
                  Next
                </button>
              </div>
            )}
          </div>
        )}

        {/* Detail modal */}
        {selectedMockup && (
          <MockupDetailModal
            mockup={selectedMockup}
            projectId={projectId}
            open={modalOpen}
            onOpenChange={setModalOpen}
            onStatusChange={() => {
              refetch()
            }}
          />
        )}

        {/* Generate mockup dialog */}
        <GenerateMockupDialog
          projectId={projectId}
          open={generateDialogOpen}
          onOpenChange={setGenerateDialogOpen}
        />

        {/* Delete confirmation dialog */}
        {showDeleteConfirm && (
          <div className="fixed inset-0 z-50 flex items-center justify-center">
            {/* Backdrop */}
            <div
              className="absolute inset-0 bg-black/80"
              onClick={() => setShowDeleteConfirm(false)}
            />

            {/* Dialog */}
            <div className="relative bg-slate-900 rounded-xl w-full max-w-md mx-4 p-6 border border-rose-500/30">
              <div className="flex items-start gap-4">
                <div className="p-3 bg-rose-500/10 rounded-lg">
                  <Trash2 className="w-6 h-6 text-rose-400" />
                </div>
                <div className="flex-1">
                  <h3 className="text-lg font-semibold text-white mb-2">
                    Delete {selectedMockups.size} mockup
                    {selectedMockups.size > 1 ? 's' : ''}?
                  </h3>
                  <p className="text-slate-400 text-sm mb-6">
                    This action cannot be undone. The selected mockup
                    {selectedMockups.size > 1 ? 's' : ''} will be permanently
                    deleted.
                  </p>
                  <div className="flex justify-end gap-3">
                    <button
                      onClick={() => setShowDeleteConfirm(false)}
                      className="btn-secondary"
                      disabled={deleteMutation.isPending}
                    >
                      Cancel
                    </button>
                    <button
                      onClick={confirmDelete}
                      disabled={deleteMutation.isPending}
                      className="bg-rose-500 hover:bg-rose-600 text-white px-4 py-2 rounded-lg transition-colors disabled:opacity-50 flex items-center gap-2"
                    >
                      {deleteMutation.isPending ? (
                        <>
                          <Loader2 className="w-4 h-4 animate-spin" />
                          Deleting...
                        </>
                      ) : (
                        <>
                          <Trash2 className="w-4 h-4" />
                          Delete
                        </>
                      )}
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Design Standards Sidebar */}
      <div className="w-80 flex-shrink-0 hidden xl:block">
        <DesignStandardsPanel projectId={projectId} />
      </div>
    </div>
  )
}
