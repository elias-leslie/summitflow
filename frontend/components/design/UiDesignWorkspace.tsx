'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { BulkActionBar } from '@/components/design/BulkActionBar'
import { CreateMockupDialog } from '@/components/design/CreateMockupDialog'
import {
  DesignFilters,
  type TypeFilter,
} from '@/components/design/DesignFilters'
import { DesignHeader, type ViewMode } from '@/components/design/DesignHeader'
import { GenerateMockupDialog } from '@/components/design/GenerateMockupDialog'
import { MockupDetailModal } from '@/components/design/MockupDetailModal'
import { MockupGrid } from '@/components/design/MockupGrid'
import {
  EmptyState,
  ErrorState,
  LoadingState,
} from '@/components/design/MockupStates'
import {
  MockupStatsGrid,
  type StatusFilter,
} from '@/components/design/MockupStatsGrid'
import { DesignStandardsPanel } from '@/components/explorer/design-standards'
import { ConfirmDeleteDialog } from '@/components/shared/ConfirmDeleteDialog'
import { useClampedPagination } from '@/hooks/useClampedPagination'
import {
  deleteMockup,
  fetchMockupStats,
  fetchMockups,
  type Mockup,
} from '@/lib/api/mockups'

interface UiDesignWorkspaceProps {
  projectId: string
}

export function UiDesignWorkspace({
  projectId,
}: UiDesignWorkspaceProps): React.ReactElement {
  const [viewMode, setViewMode] = useState<ViewMode>('grid')
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')
  const [typeFilter, setTypeFilter] = useState<TypeFilter>('all')
  const [searchQuery, setSearchQuery] = useState('')
  const [page, setPage] = useState(0)
  const [selectedMockup, setSelectedMockup] = useState<Mockup | null>(null)
  const [modalOpen, setModalOpen] = useState(false)
  const [generateDialogOpen, setGenerateDialogOpen] = useState(false)
  const [createDialogOpen, setCreateDialogOpen] = useState(false)
  const [selectMode, setSelectMode] = useState(false)
  const [selectedMockups, setSelectedMockups] = useState<Set<string>>(new Set())
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)
  const [iterationParentMockup, setIterationParentMockup] =
    useState<Mockup | null>(null)
  const pageSize = 24
  const queryClient = useQueryClient()

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

  const { data: stats } = useQuery({
    queryKey: ['mockup-stats', projectId],
    queryFn: () => fetchMockupStats(projectId),
  })

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

  const mockups = mockupsData?.items ?? []
  const totalCount = mockupsData?.total ?? 0
  useClampedPagination({
    page,
    setPage,
    totalCount,
    pageSize,
  })

  const toggleSelection = (mockupId: string): void => {
    setSelectedMockups((prev) => {
      const next = new Set(prev)
      if (next.has(mockupId)) next.delete(mockupId)
      else next.add(mockupId)
      return next
    })
  }

  return (
    <div className="flex h-full gap-4">
      <div className="flex min-w-0 flex-1 flex-col">
        <DesignHeader
          title="UI Design"
          subtitle="Analyze live pages, capture hand-authored concepts, and move mockups through the normal review flow."
          totalLabel={
            stats?.total !== undefined ? `${stats.total} mockups` : undefined
          }
          primaryActionLabel="Analyze Page"
          viewMode={viewMode}
          selectMode={selectMode}
          hasItems={mockups.length > 0}
          onViewModeChange={setViewMode}
          onSelectModeToggle={() => setSelectMode(true)}
          onCancelSelectMode={() => {
            setSelectMode(false)
            setSelectedMockups(new Set())
          }}
          onPrimaryAction={() => setGenerateDialogOpen(true)}
          extraActions={
            !selectMode ? (
              <button
                type="button"
                onClick={() => {
                  setIterationParentMockup(null)
                  setCreateDialogOpen(true)
                }}
                className="btn-secondary"
              >
                New Concept
              </button>
            ) : null
          }
        />

        {stats && (
          <MockupStatsGrid
            byStatus={stats.by_status}
            onStatusClick={(status) => {
              setStatusFilter(status)
              setPage(0)
            }}
          />
        )}

        <DesignFilters
          searchQuery={searchQuery}
          statusFilter={statusFilter}
          typeFilter={typeFilter}
          searchPlaceholder="Search UI mockups..."
          onSearchChange={(query) => {
            setSearchQuery(query)
            setPage(0)
          }}
          onStatusFilterChange={(status) => {
            setStatusFilter(status)
            setPage(0)
          }}
          onTypeFilterChange={(type) => {
            setTypeFilter(type)
            setPage(0)
          }}
        />

        {selectMode && selectedMockups.size > 0 && (
          <BulkActionBar
            selectedCount={selectedMockups.size}
            isDeleting={deleteMutation.isPending}
            onDelete={() => setShowDeleteConfirm(true)}
          />
        )}

        {isLoading && <LoadingState />}
        {error && (
          <ErrorState
            error={error}
            onRetry={() => refetch()}
            title="Failed to load UI mockups"
          />
        )}
        {!isLoading && !error && mockups.length === 0 && (
          <EmptyState
            title="No UI mockups yet"
            description="Use Analyze Page for screenshot-based audits or New Concept for hand-authored HTML mockups and design notes."
          />
        )}
        {!isLoading && !error && mockups.length > 0 && (
          <MockupGrid
            mockups={mockups}
            viewMode={viewMode}
            selectMode={selectMode}
            selectedMockups={selectedMockups}
            totalCount={totalCount}
            pageSize={pageSize}
            page={page}
            onMockupClick={(mockup) => {
              if (selectMode) {
                toggleSelection(mockup.mockup_id)
                return
              }
              setSelectedMockup(mockup)
              setModalOpen(true)
            }}
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
            onCreateIteration={(mockup) => {
              setIterationParentMockup(mockup)
              setCreateDialogOpen(true)
            }}
          />
        )}

        <GenerateMockupDialog
          projectId={projectId}
          open={generateDialogOpen}
          onOpenChange={setGenerateDialogOpen}
        />

        <CreateMockupDialog
          projectId={projectId}
          open={createDialogOpen}
          onOpenChange={(open) => {
            setCreateDialogOpen(open)
            if (!open) {
              setIterationParentMockup(null)
            }
          }}
          parentMockup={iterationParentMockup}
          onCreated={(mockup) => {
            setSelectedMockup(mockup)
            setModalOpen(true)
          }}
        />

        {showDeleteConfirm && (
          <ConfirmDeleteDialog
            entityType="mockups"
            count={selectedMockups.size}
            isDeleting={deleteMutation.isPending}
            onConfirm={() => deleteMutation.mutate(Array.from(selectedMockups))}
            onCancel={() => setShowDeleteConfirm(false)}
          />
        )}
      </div>

      <div className="hidden w-80 flex-shrink-0 xl:block">
        <DesignStandardsPanel projectId={projectId} />
      </div>
    </div>
  )
}
