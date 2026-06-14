'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { RefreshCw } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { BulkActionBar } from '@/components/design/BulkActionBar'
import { CreateMockupDialog } from '@/components/design/CreateMockupDialog'
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
  rateMockup,
} from '@/lib/api/mockups'
import {
  fetchViewerMockupHistory,
  fetchViewerMockupStats,
  fetchViewerMockups,
  getViewerMockupImageUrl,
  getViewerScreenshotUrl,
  rateViewerMockup,
} from '@/lib/api/viewer'

interface UiDesignWorkspaceProps {
  projectId: string
  readOnly?: boolean
}

type TypeFilter =
  | 'all'
  | 'component'
  | 'page'
  | 'layout'
  | 'icon'
  | 'illustration'
  | 'sprite'
  | 'sheet'
type MockupSortFilter = 'created_desc' | 'rating_average' | 'rating_count'

export function UiDesignWorkspace({
  projectId,
  readOnly = false,
}: UiDesignWorkspaceProps): React.ReactElement {
  const [viewMode, setViewMode] = useState<ViewMode>('grid')
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')
  const [typeFilter, setTypeFilter] = useState<TypeFilter>('all')
  const [sortBy, setSortBy] = useState<MockupSortFilter>('created_desc')
  const [searchQuery, setSearchQuery] = useState('')
  const [page, setPage] = useState(0)
  const [selectedMockup, setSelectedMockup] = useState<Mockup | null>(null)
  const [modalOpen, setModalOpen] = useState(false)
  const [pendingModalNavigation, setPendingModalNavigation] = useState<
    'previous' | 'next' | null
  >(null)
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
    isFetching,
    error,
    refetch,
  } = useQuery({
    queryKey: [
      'mockups',
      readOnly ? 'viewer' : 'owner',
      projectId,
      statusFilter,
      typeFilter,
      sortBy,
      searchQuery,
      page,
    ],
    queryFn: () =>
      (readOnly ? fetchViewerMockups : fetchMockups)(projectId, {
        limit: pageSize,
        offset: page * pageSize,
        status: statusFilter === 'all' ? undefined : statusFilter,
        mockup_type: typeFilter === 'all' ? undefined : typeFilter,
        search: searchQuery || undefined,
        sort_by: sortBy,
      }),
  })

  const { data: stats, refetch: refetchStats } = useQuery({
    queryKey: ['mockup-stats', readOnly ? 'viewer' : 'owner', projectId],
    queryFn: () =>
      (readOnly ? fetchViewerMockupStats : fetchMockupStats)(projectId),
  })

  const deleteMutation = useMutation({
    mutationFn: async (mockupIds: string[]) => {
      await Promise.all(mockupIds.map((id) => deleteMockup(projectId, id)))
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['mockups'] })
      queryClient.invalidateQueries({ queryKey: ['mockup-stats'] })
      setSelectedMockups(new Set())
      setSelectMode(false)
      setShowDeleteConfirm(false)
    },
  })

  const applyUpdatedMockup = (updatedMockup: Mockup): void => {
    setSelectedMockup((current) =>
      current?.mockup_id === updatedMockup.mockup_id ? updatedMockup : current,
    )
    queryClient.invalidateQueries({ queryKey: ['mockups'] })
    queryClient.invalidateQueries({ queryKey: ['mockup-stats'] })
    refetch()
  }

  const ratingMutation = useMutation({
    mutationFn: async ({
      mockupId,
      rating,
    }: {
      mockupId: string
      rating: number
    }) =>
      (readOnly ? rateViewerMockup : rateMockup)(projectId, mockupId, rating),
    onSuccess: applyUpdatedMockup,
  })

  const mockups = mockupsData?.items ?? []
  const totalCount = mockupsData?.total ?? 0
  const selectedMockupIndex = selectedMockup
    ? mockups.findIndex(
        (mockup) => mockup.mockup_id === selectedMockup.mockup_id,
      )
    : -1
  const selectedMockupPosition =
    selectedMockupIndex >= 0 ? page * pageSize + selectedMockupIndex + 1 : 0

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

  useEffect(() => {
    if (
      !modalOpen ||
      !pendingModalNavigation ||
      isFetching ||
      mockups.length === 0
    ) {
      return
    }

    setSelectedMockup(
      pendingModalNavigation === 'next'
        ? mockups[0]
        : mockups[mockups.length - 1],
    )
    setPendingModalNavigation(null)
  }, [isFetching, mockups, modalOpen, pendingModalNavigation])

  const handleRefresh = useCallback(async (): Promise<void> => {
    await Promise.all([refetch(), refetchStats()])
  }, [refetch, refetchStats])

  const handlePreviousMockup = useCallback((): void => {
    if (selectedMockupIndex > 0) {
      setSelectedMockup(mockups[selectedMockupIndex - 1])
      return
    }

    if (page > 0) {
      setPendingModalNavigation('previous')
      setPage(page - 1)
    }
  }, [mockups, page, selectedMockupIndex])

  const handleNextMockup = useCallback((): void => {
    if (selectedMockupIndex >= 0 && selectedMockupIndex < mockups.length - 1) {
      setSelectedMockup(mockups[selectedMockupIndex + 1])
      return
    }

    if ((page + 1) * pageSize < totalCount) {
      setPendingModalNavigation('next')
      setPage(page + 1)
    }
  }, [mockups, page, pageSize, selectedMockupIndex, totalCount])

  const modalNavigation = useMemo(() => {
    if (!selectedMockup || totalCount <= 1 || selectedMockupPosition <= 0) {
      return undefined
    }

    return {
      currentIndex: selectedMockupPosition,
      totalCount,
      canGoPrevious: selectedMockupPosition > 1,
      canGoNext:
        selectedMockupPosition > 0 && selectedMockupPosition < totalCount,
      onPrevious: handlePreviousMockup,
      onNext: handleNextMockup,
    }
  }, [
    handleNextMockup,
    handlePreviousMockup,
    selectedMockup,
    selectedMockupPosition,
    totalCount,
  ])

  return (
    <div className="flex h-full gap-4">
      <div className="flex min-w-0 flex-1 flex-col">
        <DesignHeader
          title="UI Design"
          subtitle={
            readOnly
              ? 'Browse shared UI mockups, review details, and rate without owner-only controls.'
              : 'Analyze live pages, capture hand-authored concepts, and move mockups through the normal review flow.'
          }
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
          readOnly={readOnly}
          extraActions={
            !selectMode ? (
              <>
                <button
                  type="button"
                  onClick={() => void handleRefresh()}
                  disabled={isFetching}
                  aria-label="Refresh mockups"
                  title="Refresh mockups"
                  className="btn-secondary flex items-center gap-2 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  <RefreshCw
                    className={`h-4 w-4 ${isFetching ? 'animate-spin' : ''}`}
                  />
                  Refresh
                </button>
                {!readOnly && (
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
                )}
              </>
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

        <div className="card mb-6 grid grid-cols-1 gap-3 p-4 lg:grid-cols-2 xl:grid-cols-4">
          <input
            value={searchQuery}
            onChange={(event) => {
              setSearchQuery(event.target.value)
              setPage(0)
            }}
            placeholder="Search UI mockups..."
            className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100 xl:col-span-1"
          />
          <select
            value={statusFilter}
            onChange={(event) => {
              setStatusFilter(event.target.value as StatusFilter)
              setPage(0)
            }}
            aria-label="Filter by status"
            className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100 focus-visible:outline-none focus-visible:border-phosphor-500/50 focus-visible:ring-1 focus-visible:ring-phosphor-500/20 transition-colors"
          >
            <option value="all">All Statuses</option>
            <option value="generated">Generated</option>
            <option value="pending_approval">Pending Approval</option>
            <option value="approved">Approved</option>
            <option value="rejected">Rejected</option>
            <option value="applied">Applied</option>
            <option value="archived">Archived</option>
          </select>
          <select
            value={typeFilter}
            onChange={(event) => {
              setTypeFilter(event.target.value as TypeFilter)
              setPage(0)
            }}
            aria-label="Filter by type"
            className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100 focus-visible:outline-none focus-visible:border-phosphor-500/50 focus-visible:ring-1 focus-visible:ring-phosphor-500/20 transition-colors"
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
          <select
            value={sortBy}
            onChange={(event) => {
              setSortBy(event.target.value as MockupSortFilter)
              setPage(0)
            }}
            aria-label="Sort UI mockups"
            className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100 focus-visible:outline-none focus-visible:border-phosphor-500/50 focus-visible:ring-1 focus-visible:ring-phosphor-500/20 transition-colors"
          >
            <option value="created_desc">Newest</option>
            <option value="rating_average">Highest rated</option>
            <option value="rating_count">Most ratings</option>
          </select>
        </div>

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
            description={
              readOnly
                ? 'No shared UI mockups are available for this project yet.'
                : 'Use Analyze Page for screenshot-based audits or New Concept for hand-authored HTML mockups and design notes.'
            }
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
            getImageUrl={readOnly ? getViewerMockupImageUrl : undefined}
            isRating={ratingMutation.isPending}
            onRate={(mockupId, rating) =>
              ratingMutation.mutate({ mockupId, rating })
            }
          />
        )}

        {selectedMockup && (
          <MockupDetailModal
            mockup={selectedMockup}
            projectId={projectId}
            open={modalOpen}
            onOpenChange={setModalOpen}
            onStatusChange={() => void handleRefresh()}
            onRate={(mockupId, rating) =>
              ratingMutation.mutate({ mockupId, rating })
            }
            onCommentsChanged={() => void handleRefresh()}
            onCreateIteration={(mockup) => {
              setIterationParentMockup(mockup)
              setCreateDialogOpen(true)
            }}
            onSelectMockup={setSelectedMockup}
            navigation={modalNavigation}
            readOnly={readOnly}
            fetchHistory={readOnly ? fetchViewerMockupHistory : undefined}
            getImageUrl={readOnly ? getViewerMockupImageUrl : undefined}
            getScreenshotUrl={readOnly ? getViewerScreenshotUrl : undefined}
            isRating={ratingMutation.isPending}
          />
        )}

        {!readOnly && (
          <GenerateMockupDialog
            projectId={projectId}
            open={generateDialogOpen}
            onOpenChange={setGenerateDialogOpen}
          />
        )}

        {!readOnly && (
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
        )}

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

      {!readOnly && (
        <div className="hidden w-80 flex-shrink-0 xl:block">
          <DesignStandardsPanel projectId={projectId} />
        </div>
      )}
    </div>
  )
}
