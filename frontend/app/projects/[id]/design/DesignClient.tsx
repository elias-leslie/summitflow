'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useParams } from 'next/navigation'
import { useState } from 'react'
import { BulkActionBar } from '@/components/design/BulkActionBar'
import { ConfirmDeleteDialog } from '@/components/shared/ConfirmDeleteDialog'
import { DesignFilters, type TypeFilter } from '@/components/design/DesignFilters'
import { DesignHeader, type ViewMode } from '@/components/design/DesignHeader'
import { GenerateAssetDialog } from '@/components/design/GenerateAssetDialog'
import { GenerateMockupDialog } from '@/components/design/GenerateMockupDialog'
import { MockupDetailModal } from '@/components/design/MockupDetailModal'
import { MockupGrid } from '@/components/design/MockupGrid'
import { MockupStatsGrid, type StatusFilter } from '@/components/design/MockupStatsGrid'
import { EmptyState, ErrorState, LoadingState } from '@/components/design/MockupStates'
import { DesignStandardsPanel } from '@/components/explorer/design-standards'
import {
  deleteMockup,
  fetchMockupStats,
  fetchMockups,
  type Mockup,
} from '@/lib/api/mockups'

export function DesignClient(): React.ReactElement {
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
  const [generateAssetDialogOpen, setGenerateAssetDialogOpen] = useState(false)

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

  const handleMockupClick = (mockup: Mockup): void => {
    if (selectMode) {
      toggleMockupSelection(mockup.mockup_id)
    } else {
      setSelectedMockup(mockup)
      setModalOpen(true)
    }
  }

  const toggleMockupSelection = (mockupId: string): void => {
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

  const handleBulkDelete = (): void => {
    if (selectedMockups.size === 0) return
    setShowDeleteConfirm(true)
  }

  const confirmDelete = (): void => {
    deleteMutation.mutate(Array.from(selectedMockups))
  }

  const cancelSelectMode = (): void => {
    setSelectMode(false)
    setSelectedMockups(new Set())
  }

  const handleSearchChange = (query: string): void => {
    setSearchQuery(query)
    setPage(0)
  }

  const handleStatusFilterChange = (status: StatusFilter): void => {
    setStatusFilter(status)
    setPage(0)
  }

  const handleTypeFilterChange = (type: TypeFilter): void => {
    setTypeFilter(type)
    setPage(0)
  }

  return (
    <div className="h-full flex gap-4 p-4">
      {/* Main content */}
      <div className="flex-1 flex flex-col min-w-0">
        <DesignHeader
          totalMockups={stats?.total}
          viewMode={viewMode}
          selectMode={selectMode}
          hasMockups={mockups.length > 0}
          onViewModeChange={setViewMode}
          onSelectModeToggle={() => setSelectMode(true)}
          onCancelSelectMode={cancelSelectMode}
          onGenerateClick={() => setGenerateDialogOpen(true)}
          onGenerateAssetClick={() => setGenerateAssetDialogOpen(true)}
        />

        {stats && (
          <MockupStatsGrid
            byStatus={stats.by_status}
            onStatusClick={handleStatusFilterChange}
          />
        )}

        <DesignFilters
          searchQuery={searchQuery}
          statusFilter={statusFilter}
          typeFilter={typeFilter}
          onSearchChange={handleSearchChange}
          onStatusFilterChange={handleStatusFilterChange}
          onTypeFilterChange={handleTypeFilterChange}
        />

        {selectMode && selectedMockups.size > 0 && (
          <BulkActionBar
            selectedCount={selectedMockups.size}
            isDeleting={deleteMutation.isPending}
            onDelete={handleBulkDelete}
          />
        )}

        {isLoading && <LoadingState />}

        {error && <ErrorState error={error} onRetry={() => refetch()} />}

        {!isLoading && !error && mockups.length === 0 && <EmptyState />}

        {!isLoading && !error && mockups.length > 0 && (
          <MockupGrid
            mockups={mockups}
            viewMode={viewMode}
            selectMode={selectMode}
            selectedMockups={selectedMockups}
            totalCount={totalCount}
            pageSize={pageSize}
            page={page}
            onMockupClick={handleMockupClick}
            onPageChange={setPage}
          />
        )}

        {selectedMockup && (
          <MockupDetailModal
            mockup={selectedMockup}
            projectId={projectId}
            open={modalOpen}
            onOpenChange={setModalOpen}
            onStatusChange={() => refetch()}
          />
        )}

        <GenerateMockupDialog
          projectId={projectId}
          open={generateDialogOpen}
          onOpenChange={setGenerateDialogOpen}
        />

        <GenerateAssetDialog
          projectId={projectId}
          open={generateAssetDialogOpen}
          onOpenChange={setGenerateAssetDialogOpen}
        />

        {showDeleteConfirm && (
          <ConfirmDeleteDialog
            entityType="mockups"
            count={selectedMockups.size}
            isDeleting={deleteMutation.isPending}
            onConfirm={confirmDelete}
            onCancel={() => setShowDeleteConfirm(false)}
          />
        )}
      </div>

      {/* Design Standards Sidebar */}
      <div className="w-80 flex-shrink-0 hidden xl:block">
        <DesignStandardsPanel projectId={projectId} />
      </div>
    </div>
  )
}
