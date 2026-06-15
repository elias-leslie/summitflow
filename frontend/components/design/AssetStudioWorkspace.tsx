'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import {
  ChevronLeft,
  ChevronRight,
  Download,
  ExternalLink,
  FileImage,
  Folder,
  FolderTree,
  Image as ImageIcon,
  Layers3,
  Maximize2,
  MessageSquare,
  Package,
  Tags,
  X,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { ConfirmDeleteDialog } from '@/components/shared/ConfirmDeleteDialog'
import { useClampedPagination } from '@/hooks/useClampedPagination'
import {
  addDesignAssetComment,
  type DesignAsset,
  type DesignAssetExport,
  deleteDesignAsset,
  deleteDesignAssetComment,
  exportSpriteFrames,
  fetchDesignAssetComments,
  fetchDesignAssetExports,
  fetchDesignAssetStats,
  fetchDesignAssets,
  getDesignAssetImageUrl,
  rateDesignAsset,
  updateDesignAssetComment,
  updateDesignAssetStatus,
} from '@/lib/api/design-assets'
import {
  addViewerDesignAssetComment,
  deleteViewerDesignAssetComment,
  fetchViewerDesignAssetComments,
  fetchViewerDesignAssetStats,
  fetchViewerDesignAssets,
  getViewerDesignAssetImageUrl,
  rateViewerDesignAsset,
  updateViewerDesignAssetComment,
} from '@/lib/api/viewer'
import { ArtifactComments } from './ArtifactComments'
import { DesignHeader, type ViewMode } from './DesignHeader'
import { GenerateAssetDialog } from './GenerateAssetDialog'
import { EmptyState, ErrorState, LoadingState } from './MockupStates'
import { StarRating } from './StarRating'

type AssetStatusFilter =
  | 'all'
  | 'generated'
  | 'approved'
  | 'rejected'
  | 'archived'
  | 'exported'
type AssetTypeFilter =
  | 'all'
  | 'sprite'
  | 'sprite_sheet'
  | 'portrait'
  | 'environment'
  | 'icon'
  | 'illustration'
  | 'ui_texture'
  | 'marketing_mockup'
  | 'tile_set'
  | 'concept_art'
type WorkflowFilter = 'all' | 'concept' | 'production' | 'marketing' | 'ui'
type AssetSortFilter = 'created_desc' | 'rating_average' | 'rating_count'
type AssetStudioSection = 'review' | 'production'

interface AssetStudioWorkspaceProps {
  projectId: string
  readOnly?: boolean
}

interface AssetModalNavigation {
  currentIndex: number
  totalCount: number
  canGoPrevious: boolean
  canGoNext: boolean
  onPrevious: () => void
  onNext: () => void
}

export function AssetStudioWorkspace({
  projectId,
  readOnly = false,
}: AssetStudioWorkspaceProps): React.ReactElement {
  const [viewMode, setViewMode] = useState<ViewMode>('grid')
  const [statusFilter, setStatusFilter] = useState<AssetStatusFilter>('all')
  const [typeFilter, setTypeFilter] = useState<AssetTypeFilter>('all')
  const [workflowFilter, setWorkflowFilter] = useState<WorkflowFilter>('all')
  const [sortBy, setSortBy] = useState<AssetSortFilter>('created_desc')
  const [searchQuery, setSearchQuery] = useState('')
  const [page, setPage] = useState(0)
  const [activeSection, setActiveSection] =
    useState<AssetStudioSection>('review')
  const [selectedProductionFolder, setSelectedProductionFolder] =
    useState('all')
  const [dialogOpen, setDialogOpen] = useState(false)
  const [selectedAsset, setSelectedAsset] = useState<DesignAsset | null>(null)
  const [previewAsset, setPreviewAsset] = useState<DesignAsset | null>(null)
  const [pendingPreviewNavigation, setPendingPreviewNavigation] = useState<
    'previous' | 'next' | null
  >(null)
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)
  const pageSize = 24
  const queryClient = useQueryClient()

  const {
    data: assetData,
    isLoading,
    isFetching,
    error,
    refetch,
  } = useQuery({
    queryKey: [
      'design-assets',
      readOnly ? 'viewer' : 'owner',
      projectId,
      statusFilter,
      typeFilter,
      workflowFilter,
      sortBy,
      searchQuery,
      page,
    ],
    queryFn: () =>
      (readOnly ? fetchViewerDesignAssets : fetchDesignAssets)(projectId, {
        limit: pageSize,
        offset: page * pageSize,
        status: statusFilter === 'all' ? undefined : statusFilter,
        asset_type: typeFilter === 'all' ? undefined : typeFilter,
        workflow: workflowFilter === 'all' ? undefined : workflowFilter,
        search: searchQuery || undefined,
        sort_by: sortBy,
      }),
  })

  const { data: stats } = useQuery({
    queryKey: ['design-assets-stats', readOnly ? 'viewer' : 'owner', projectId],
    queryFn: () =>
      (readOnly ? fetchViewerDesignAssetStats : fetchDesignAssetStats)(
        projectId,
      ),
  })

  const {
    data: productionAssetData,
    isLoading: isProductionLoading,
    error: productionError,
    refetch: refetchProductionAssets,
  } = useQuery({
    queryKey: [
      'design-assets-production',
      readOnly ? 'viewer' : 'owner',
      projectId,
    ],
    queryFn: () =>
      (readOnly ? fetchViewerDesignAssets : fetchDesignAssets)(projectId, {
        limit: 500,
        offset: 0,
        workflow: 'production',
        sort_by: 'created_desc',
      }),
  })

  const productionAssets = productionAssetData?.items ?? []
  const productionTree = useMemo(
    () => buildProductionAssetTree(productionAssets),
    [productionAssets],
  )
  const productionPreviewAssets = useMemo(
    () =>
      selectedProductionFolder === 'all'
        ? productionAssets
        : productionAssets.filter(
            (asset) =>
              productionAssetFolderKey(asset) === selectedProductionFolder,
          ),
    [productionAssets, selectedProductionFolder],
  )

  const applyUpdatedAsset = (updatedAsset: DesignAsset): void => {
    setSelectedAsset((current) =>
      current?.asset_id === updatedAsset.asset_id ? updatedAsset : current,
    )
    setPreviewAsset((current) =>
      current?.asset_id === updatedAsset.asset_id ? updatedAsset : current,
    )
    queryClient.invalidateQueries({ queryKey: ['design-assets'] })
    queryClient.invalidateQueries({ queryKey: ['design-assets-production'] })
    queryClient.invalidateQueries({
      queryKey: ['design-assets-stats'],
    })
    refetch()
    refetchProductionAssets()
  }

  const statusMutation = useMutation({
    mutationFn: async ({
      assetId,
      status,
    }: {
      assetId: string
      status: string
    }) =>
      updateDesignAssetStatus(
        projectId,
        assetId,
        status,
        status === 'approved' ? 'codex' : undefined,
      ),
    onSuccess: applyUpdatedAsset,
  })

  const ratingMutation = useMutation({
    mutationFn: async ({
      assetId,
      rating,
    }: {
      assetId: string
      rating: number
    }) =>
      (readOnly ? rateViewerDesignAsset : rateDesignAsset)(
        projectId,
        assetId,
        rating,
      ),
    onSuccess: applyUpdatedAsset,
  })

  const deleteMutation = useMutation({
    mutationFn: async (assetId: string) =>
      deleteDesignAsset(projectId, assetId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['design-assets'] })
      queryClient.invalidateQueries({ queryKey: ['design-assets-production'] })
      queryClient.invalidateQueries({
        queryKey: ['design-assets-stats'],
      })
      setShowDeleteConfirm(false)
      setSelectedAsset(null)
    },
  })

  const exportMutation = useMutation({
    mutationFn: async (assetId: string) =>
      exportSpriteFrames(projectId, assetId),
    onSuccess: () => {
      if (selectedAsset) {
        queryClient.invalidateQueries({
          queryKey: ['design-asset-exports', projectId, selectedAsset.asset_id],
        })
      }
      queryClient.invalidateQueries({ queryKey: ['design-assets'] })
      queryClient.invalidateQueries({ queryKey: ['design-assets-production'] })
      queryClient.invalidateQueries({
        queryKey: ['design-assets-stats'],
      })
    },
  })

  const assets = assetData?.items ?? []
  const totalCount = assetData?.total ?? 0
  const previewAssetIndex = previewAsset
    ? assets.findIndex((asset) => asset.asset_id === previewAsset.asset_id)
    : -1
  const previewAssetPosition =
    previewAssetIndex >= 0 ? page * pageSize + previewAssetIndex + 1 : 0
  const totalPages = useClampedPagination({
    page,
    setPage,
    totalCount,
    pageSize,
  })

  useEffect(() => {
    if (
      !previewAsset ||
      !pendingPreviewNavigation ||
      isFetching ||
      assets.length === 0
    ) {
      return
    }

    const nextAsset =
      pendingPreviewNavigation === 'next'
        ? assets[0]
        : assets[assets.length - 1]
    setSelectedAsset(nextAsset)
    setPreviewAsset(nextAsset)
    setPendingPreviewNavigation(null)
  }, [assets, isFetching, pendingPreviewNavigation, previewAsset])

  const showPreviousPreviewAsset = (): void => {
    if (previewAssetIndex > 0) {
      const nextAsset = assets[previewAssetIndex - 1]
      setSelectedAsset(nextAsset)
      setPreviewAsset(nextAsset)
      return
    }

    if (page > 0) {
      setPendingPreviewNavigation('previous')
      setPage(page - 1)
    }
  }

  const showNextPreviewAsset = (): void => {
    if (previewAssetIndex >= 0 && previewAssetIndex < assets.length - 1) {
      const nextAsset = assets[previewAssetIndex + 1]
      setSelectedAsset(nextAsset)
      setPreviewAsset(nextAsset)
      return
    }

    if ((page + 1) * pageSize < totalCount) {
      setPendingPreviewNavigation('next')
      setPage(page + 1)
    }
  }

  const previewNavigation: AssetModalNavigation | undefined =
    previewAsset && totalCount > 1 && previewAssetPosition > 0
      ? {
          currentIndex: previewAssetPosition,
          totalCount,
          canGoPrevious: previewAssetPosition > 1,
          canGoNext: previewAssetPosition < totalCount,
          onPrevious: showPreviousPreviewAsset,
          onNext: showNextPreviewAsset,
        }
      : undefined

  const imageUrlForAsset = (asset: DesignAsset): string =>
    readOnly
      ? getViewerDesignAssetImageUrl(projectId, asset.asset_id)
      : getDesignAssetImageUrl(projectId, asset.asset_id)

  return (
    <div className="flex h-full flex-col min-w-0">
      <DesignHeader
        title="Asset Studio"
        subtitle={
          readOnly
            ? 'Browse shared design assets, review details, and rate without owner-only controls.'
            : 'Import manual/current-agent visuals, generate Agent Hub variants, review candidates, and export approved sprite sheets.'
        }
        totalLabel={
          stats?.total !== undefined ? `${stats.total} assets` : undefined
        }
        primaryActionLabel="Add Assets"
        viewMode={viewMode}
        selectMode={false}
        hasItems={assets.length > 0}
        onViewModeChange={setViewMode}
        onSelectModeToggle={() => undefined}
        onCancelSelectMode={() => undefined}
        onPrimaryAction={() => setDialogOpen(true)}
        readOnly={readOnly}
      />

      <div className="mb-6 flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={() => setActiveSection('review')}
          className={assetStudioSectionClass(activeSection === 'review')}
        >
          Review Board
        </button>
        <button
          type="button"
          onClick={() => setActiveSection('production')}
          className={assetStudioSectionClass(activeSection === 'production')}
        >
          Production Assets
        </button>
        <span className="text-sm text-slate-500">
          Production Assets shows workflow=production records in a file tree
          with expandable previews.
        </span>
      </div>

      <div className="mb-6 grid grid-cols-1 gap-4 lg:grid-cols-4">
        <StudioStat
          icon={<Package className="h-4 w-4 text-cyan-300" />}
          label="Generated"
          value={stats?.by_status.generated ?? 0}
        />
        <StudioStat
          icon={<Layers3 className="h-4 w-4 text-emerald-300" />}
          label="Sprite Sheets"
          value={stats?.by_type.sprite_sheet ?? 0}
        />
        <StudioStat
          icon={<ImageIcon className="h-4 w-4 text-amber-300" />}
          label="Environments"
          value={stats?.by_type.environment ?? 0}
        />
        <StudioStat
          icon={<Tags className="h-4 w-4 text-orange-300" />}
          label="Models"
          value={stats?.unique_models ?? 0}
        />
      </div>

      {activeSection === 'review' && (
        <div className="mb-6 grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
          <div className="card grid grid-cols-1 gap-3 p-4 lg:grid-cols-2 xl:grid-cols-6">
            <input
              value={searchQuery}
              onChange={(event) => {
                setSearchQuery(event.target.value)
                setPage(0)
              }}
              placeholder="Search generated assets..."
              className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100 xl:col-span-2"
            />
            <select
              value={statusFilter}
              onChange={(event) => {
                setStatusFilter(event.target.value as AssetStatusFilter)
                setPage(0)
              }}
              className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100 focus-visible:outline-none focus-visible:border-phosphor-500/50 focus-visible:ring-1 focus-visible:ring-phosphor-500/20 transition-colors"
            >
              <option value="all">All Statuses</option>
              <option value="generated">Generated</option>
              <option value="approved">Approved</option>
              <option value="rejected">Rejected</option>
              <option value="exported">Exported</option>
              <option value="archived">Archived</option>
            </select>
            <select
              value={typeFilter}
              onChange={(event) => {
                setTypeFilter(event.target.value as AssetTypeFilter)
                setPage(0)
              }}
              className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100 focus-visible:outline-none focus-visible:border-phosphor-500/50 focus-visible:ring-1 focus-visible:ring-phosphor-500/20 transition-colors"
            >
              <option value="all">All Asset Types</option>
              <option value="sprite">Sprite</option>
              <option value="sprite_sheet">Sprite Sheet</option>
              <option value="portrait">Portrait</option>
              <option value="environment">Environment</option>
              <option value="icon">Icon</option>
              <option value="illustration">Illustration</option>
              <option value="ui_texture">UI Texture</option>
              <option value="marketing_mockup">Marketing Mockup</option>
              <option value="tile_set">Tile Set</option>
              <option value="concept_art">Concept Art</option>
            </select>
            <select
              value={workflowFilter}
              onChange={(event) => {
                setWorkflowFilter(event.target.value as WorkflowFilter)
                setPage(0)
              }}
              className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100 focus-visible:outline-none focus-visible:border-phosphor-500/50 focus-visible:ring-1 focus-visible:ring-phosphor-500/20 transition-colors"
            >
              <option value="all">All Workflows</option>
              <option value="concept">Concept</option>
              <option value="production">Production</option>
              <option value="marketing">Marketing</option>
              <option value="ui">UI</option>
            </select>
            <select
              value={sortBy}
              onChange={(event) => {
                setSortBy(event.target.value as AssetSortFilter)
                setPage(0)
              }}
              className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100 focus-visible:outline-none focus-visible:border-phosphor-500/50 focus-visible:ring-1 focus-visible:ring-phosphor-500/20 transition-colors"
            >
              <option value="created_desc">Newest</option>
              <option value="rating_average">Highest rated</option>
              <option value="rating_count">Most ratings</option>
            </select>
          </div>

          <aside className="card p-4">
            <p className="text-xs uppercase tracking-[0.22em] text-cyan-300">
              Production Playbook
            </p>
            <h3 className="mt-2 text-lg font-semibold text-slate-100">
              Asset Direction
            </h3>
            <div className="mt-4 space-y-4 text-sm text-slate-300">
              <p>
                Use the source gate first: manual/current-agent imports stay in
                Asset Studio review, while Agent Hub generation starts from a
                prompt.
              </p>
              <p>
                Use transparent backgrounds for sprites, icons, portraits, and
                UI textures.
              </p>
              <p>
                Use `production` workflow for in-game art, `marketing` for promo
                mockups, and `ui` for product-facing visuals.
              </p>
              <p>
                Sprite sheets become exportable once rows, columns, frame sizes,
                and animation labels are defined.
              </p>
            </div>
          </aside>
        </div>
      )}

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="min-h-0">
          {activeSection === 'review' ? (
            <>
              {isLoading && <LoadingState />}
              {error && (
                <ErrorState
                  error={error}
                  onRetry={() => refetch()}
                  title="Failed to load design assets"
                />
              )}
              {!isLoading && !error && assets.length === 0 && (
                <EmptyState
                  title="No design assets yet"
                  description="Import manual assets or generate Agent Hub variants, then review sprites, environments, icon sets, tile sets, and sprite sheets here."
                />
              )}
              {!isLoading && !error && assets.length > 0 && (
                <div className="flex-1 overflow-auto">
                  <div
                    className={
                      viewMode === 'grid'
                        ? 'grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3'
                        : 'flex flex-col gap-3'
                    }
                  >
                    {assets.map((asset) => (
                      <div
                        role="button"
                        tabIndex={0}
                        key={asset.asset_id}
                        onClick={() => {
                          setSelectedAsset(asset)
                          setPreviewAsset(asset)
                        }}
                        onKeyDown={(event) => {
                          if (event.key === 'Enter' || event.key === ' ') {
                            event.preventDefault()
                            setSelectedAsset(asset)
                            setPreviewAsset(asset)
                          }
                        }}
                        className={clsx(
                          'card cursor-pointer overflow-hidden text-left transition hover:ring-1 hover:ring-cyan-400/30',
                          viewMode === 'list' && 'flex items-center gap-4 p-3',
                        )}
                      >
                        <AssetPreview
                          asset={asset}
                          projectId={projectId}
                          imageUrl={imageUrlForAsset(asset)}
                          compact={viewMode === 'list'}
                          showWorkflowBadge
                          className={clsx(
                            'relative overflow-hidden rounded-xl bg-slate-900',
                            viewMode === 'grid'
                              ? 'aspect-video'
                              : 'h-24 w-40 flex-shrink-0',
                          )}
                        />
                        <div
                          className={viewMode === 'grid' ? 'p-4' : 'min-w-0'}
                        >
                          <div className="flex items-center justify-between gap-3">
                            <h3 className="truncate text-slate-100 font-medium">
                              {asset.name}
                            </h3>
                            <span className="text-2xs uppercase tracking-[0.18em] text-slate-500">
                              {asset.asset_type.replace('_', ' ')}
                            </span>
                          </div>
                          {asset.description && (
                            <p className="mt-2 line-clamp-2 text-sm text-slate-400">
                              {asset.description}
                            </p>
                          )}
                          <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-500">
                            <span>
                              {asset.width}x{asset.height}
                            </span>
                            <span>{asset.model ?? 'default model'}</span>
                            <span className="capitalize">{asset.status}</span>
                            {asset.comment_count > 0 && (
                              <span className="flex items-center gap-1 text-cyan-300">
                                <MessageSquare className="h-3.5 w-3.5" />
                                {asset.comment_count}
                              </span>
                            )}
                          </div>
                          <div className="mt-3">
                            <StarRating
                              average={asset.rating_average}
                              count={asset.rating_count}
                              userRating={asset.user_rating}
                              disabled={ratingMutation.isPending}
                              compact
                              onRate={(rating) =>
                                ratingMutation.mutate({
                                  assetId: asset.asset_id,
                                  rating,
                                })
                              }
                            />
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>

                  {totalCount > pageSize && (
                    <div className="mt-6 flex items-center justify-center gap-4 pb-4">
                      <button
                        type="button"
                        onClick={() => setPage(Math.max(0, page - 1))}
                        disabled={page === 0}
                        className="btn-secondary disabled:opacity-50"
                      >
                        Previous
                      </button>
                      <span className="text-slate-400">
                        Page {page + 1} of {totalPages}
                      </span>
                      <button
                        type="button"
                        onClick={() => setPage(page + 1)}
                        disabled={(page + 1) * pageSize >= totalCount}
                        className="btn-secondary disabled:opacity-50"
                      >
                        Next
                      </button>
                    </div>
                  )}
                </div>
              )}
            </>
          ) : (
            <ProductionAssetsPanel
              assets={productionPreviewAssets}
              error={productionError}
              imageUrlForAsset={imageUrlForAsset}
              isLoading={isProductionLoading}
              projectId={projectId}
              selectedFolder={selectedProductionFolder}
              setPreviewAsset={setPreviewAsset}
              setSelectedAsset={setSelectedAsset}
              tree={productionTree}
              onRetry={() => refetchProductionAssets()}
              onSelectFolder={setSelectedProductionFolder}
            />
          )}
        </div>

        <AssetInspector
          asset={selectedAsset}
          projectId={projectId}
          isExporting={exportMutation.isPending}
          isUpdating={statusMutation.isPending}
          isRating={ratingMutation.isPending}
          readOnly={readOnly}
          imageUrl={selectedAsset ? imageUrlForAsset(selectedAsset) : undefined}
          onClose={() => setSelectedAsset(null)}
          onDelete={() => setShowDeleteConfirm(true)}
          onExport={() =>
            selectedAsset && exportMutation.mutate(selectedAsset.asset_id)
          }
          onPreview={() => selectedAsset && setPreviewAsset(selectedAsset)}
          onStatusChange={(status) =>
            selectedAsset &&
            statusMutation.mutate({ assetId: selectedAsset.asset_id, status })
          }
          onRate={(rating) =>
            selectedAsset &&
            ratingMutation.mutate({ assetId: selectedAsset.asset_id, rating })
          }
        />
      </div>

      {!readOnly && (
        <GenerateAssetDialog
          projectId={projectId}
          open={dialogOpen}
          onOpenChange={setDialogOpen}
          onGenerated={async (createdAssets) => {
            queryClient.invalidateQueries({
              queryKey: ['design-assets'],
            })
            queryClient.invalidateQueries({
              queryKey: ['design-assets-production'],
            })
            queryClient.invalidateQueries({
              queryKey: ['design-assets-stats'],
            })
            if (createdAssets[0]) {
              setSelectedAsset(createdAssets[0])
              if (createdAssets[0].workflow === 'production') {
                setActiveSection('production')
              }
            }
          }}
        />
      )}

      {previewAsset && (
        <AssetDetailModal
          asset={previewAsset}
          isExporting={exportMutation.isPending}
          isUpdating={statusMutation.isPending}
          isRating={ratingMutation.isPending}
          readOnly={readOnly}
          imageUrl={imageUrlForAsset(previewAsset)}
          navigation={previewNavigation}
          onClose={() => setPreviewAsset(null)}
          onDelete={() => {
            setSelectedAsset(previewAsset)
            setShowDeleteConfirm(true)
          }}
          onExport={() => exportMutation.mutate(previewAsset.asset_id)}
          onStatusChange={(status) => {
            setSelectedAsset(previewAsset)
            statusMutation.mutate({ assetId: previewAsset.asset_id, status })
          }}
          onRate={(rating) => {
            setSelectedAsset(previewAsset)
            ratingMutation.mutate({ assetId: previewAsset.asset_id, rating })
          }}
          onCommentsChanged={() => {
            queryClient.invalidateQueries({ queryKey: ['design-assets'] })
            queryClient.invalidateQueries({
              queryKey: ['design-assets-production'],
            })
            refetch()
            refetchProductionAssets()
          }}
        />
      )}

      {!readOnly && selectedAsset && showDeleteConfirm && (
        <ConfirmDeleteDialog
          entityType="asset"
          entityName={selectedAsset.name}
          isDeleting={deleteMutation.isPending}
          onConfirm={() => deleteMutation.mutate(selectedAsset.asset_id)}
          onCancel={() => setShowDeleteConfirm(false)}
        />
      )}
    </div>
  )
}

function StudioStat({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode
  label: string
  value: number
}): React.ReactElement {
  return (
    <div className="card flex items-center gap-3 p-4">
      <div className="rounded-xl bg-slate-900 p-2">{icon}</div>
      <div>
        <div className="text-lg font-semibold text-slate-100">{value}</div>
        <div className="text-xs uppercase tracking-[0.18em] text-slate-500">
          {label}
        </div>
      </div>
    </div>
  )
}

function ProductionAssetsPanel({
  assets,
  error,
  imageUrlForAsset,
  isLoading,
  projectId,
  selectedFolder,
  setPreviewAsset,
  setSelectedAsset,
  tree,
  onRetry,
  onSelectFolder,
}: {
  assets: DesignAsset[]
  error: Error | null
  imageUrlForAsset: (asset: DesignAsset) => string
  isLoading: boolean
  projectId: string
  selectedFolder: string
  setPreviewAsset: (asset: DesignAsset) => void
  setSelectedAsset: (asset: DesignAsset) => void
  tree: ProductionAssetFolder[]
  onRetry: () => void
  onSelectFolder: (folderKey: string) => void
}): React.ReactElement {
  const selectedLabel =
    selectedFolder === 'all'
      ? 'assets/production'
      : (tree.find((folder) => folder.key === selectedFolder)?.path ??
        selectedFolder)

  if (isLoading) return <LoadingState />

  if (error) {
    return (
      <ErrorState
        error={error}
        onRetry={onRetry}
        title="Failed to load production assets"
      />
    )
  }

  return (
    <div className="grid min-h-0 gap-4 lg:grid-cols-[280px_minmax(0,1fr)]">
      <aside className="card min-h-0 overflow-auto p-4">
        <div className="flex items-center gap-2 text-cyan-300">
          <FolderTree className="h-4 w-4" />
          <p className="text-xs uppercase tracking-[0.22em]">Production Tree</p>
        </div>

        <button
          type="button"
          onClick={() => onSelectFolder('all')}
          className={productionFolderClass(selectedFolder === 'all')}
        >
          <Folder className="h-4 w-4" />
          <span className="min-w-0 flex-1 truncate">assets/production</span>
          <span className="text-xs text-slate-500">
            {tree.reduce((count, folder) => count + folder.assets.length, 0)}
          </span>
        </button>

        <div className="mt-3 space-y-2">
          {tree.map((folder) => (
            <div key={folder.key}>
              <button
                type="button"
                onClick={() => onSelectFolder(folder.key)}
                className={productionFolderClass(selectedFolder === folder.key)}
              >
                <Folder className="h-4 w-4" />
                <span className="min-w-0 flex-1 truncate">{folder.path}</span>
                <span className="text-xs text-slate-500">
                  {folder.assets.length}
                </span>
              </button>

              <div className="ml-4 mt-1 space-y-1 border-l border-slate-800 pl-3">
                {folder.assets.slice(0, 8).map((asset) => (
                  <button
                    type="button"
                    key={asset.asset_id}
                    onClick={() => {
                      setSelectedAsset(asset)
                      setPreviewAsset(asset)
                    }}
                    className="flex w-full items-center gap-2 rounded-md px-2 py-1 text-left text-xs text-slate-400 transition hover:bg-slate-900 hover:text-slate-100"
                  >
                    <FileImage className="h-3.5 w-3.5 flex-shrink-0 text-slate-500" />
                    <span className="min-w-0 flex-1 truncate">
                      {productionAssetFileName(asset)}
                    </span>
                  </button>
                ))}
                {folder.assets.length > 8 && (
                  <p className="px-2 text-xs text-slate-600">
                    +{folder.assets.length - 8} more
                  </p>
                )}
              </div>
            </div>
          ))}
        </div>
      </aside>

      <section className="card min-h-0 overflow-auto p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-xs uppercase tracking-[0.22em] text-cyan-300">
              Preview Pane
            </p>
            <h3 className="mt-1 text-lg font-semibold text-slate-100">
              {selectedLabel}
            </h3>
          </div>
          <span className="rounded-full bg-slate-900 px-3 py-1 text-xs uppercase tracking-[0.18em] text-slate-400">
            {assets.length} thumbnails
          </span>
        </div>

        {assets.length === 0 ? (
          <EmptyState
            title="No production assets yet"
            description="Generate or import assets with workflow=production to manage them here."
          />
        ) : (
          <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {assets.map((asset) => (
              <button
                type="button"
                key={asset.asset_id}
                onClick={() => {
                  setSelectedAsset(asset)
                  setPreviewAsset(asset)
                }}
                className="overflow-hidden rounded-2xl border border-slate-800 bg-slate-950 text-left transition hover:border-cyan-400/40 hover:ring-1 hover:ring-cyan-400/20"
              >
                <AssetPreview
                  asset={asset}
                  projectId={projectId}
                  imageUrl={imageUrlForAsset(asset)}
                  showWorkflowBadge
                  className="relative aspect-video overflow-hidden rounded-t-2xl bg-slate-900"
                />
                <div className="p-3">
                  <div className="flex items-center justify-between gap-2">
                    <p className="truncate text-sm font-medium text-slate-100">
                      {asset.name}
                    </p>
                    <span className="rounded-full bg-slate-900 px-2 py-0.5 text-2xs uppercase tracking-[0.16em] text-slate-500">
                      {asset.status}
                    </span>
                  </div>
                  <p className="mt-1 truncate font-mono text-xs text-slate-500">
                    {productionAssetFileName(asset)}
                  </p>
                </div>
              </button>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}

interface ProductionAssetFolder {
  key: string
  path: string
  assets: DesignAsset[]
}

function buildProductionAssetTree(
  assets: DesignAsset[],
): ProductionAssetFolder[] {
  const folders = new Map<string, ProductionAssetFolder>()

  for (const asset of assets) {
    const key = productionAssetFolderKey(asset)
    const existing = folders.get(key)
    if (existing) {
      existing.assets.push(asset)
    } else {
      folders.set(key, {
        key,
        path: `assets/production/${key}`,
        assets: [asset],
      })
    }
  }

  return Array.from(folders.values()).sort((a, b) =>
    a.path.localeCompare(b.path),
  )
}

function productionAssetFolderKey(asset: DesignAsset): string {
  return asset.asset_type || 'uncategorized'
}

function productionAssetFileName(asset: DesignAsset): string {
  const originalName = metadataText(asset, 'original_file_name')
  if (originalName) return originalName
  return `${asset.asset_id}.${isSvgAsset(asset) ? 'svg' : 'png'}`
}

function productionFolderClass(active: boolean): string {
  return clsx(
    'mt-3 flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm transition',
    active
      ? 'bg-cyan-500/10 text-cyan-100 ring-1 ring-cyan-400/30'
      : 'text-slate-300 hover:bg-slate-900 hover:text-slate-100',
  )
}

function assetStudioSectionClass(active: boolean): string {
  return clsx(
    'rounded-full border px-4 py-2 text-sm font-medium transition',
    active
      ? 'border-cyan-400/50 bg-cyan-500/15 text-cyan-100 shadow-[0_0_18px_rgba(34,211,238,0.12)]'
      : 'border-slate-700 bg-slate-900/70 text-slate-400 hover:border-slate-600 hover:text-slate-100',
  )
}

function AssetPreview({
  asset,
  projectId,
  imageUrl,
  className,
  compact = false,
  large = false,
  showWorkflowBadge = false,
}: {
  asset: DesignAsset
  projectId: string
  imageUrl?: string
  className: string
  compact?: boolean
  large?: boolean
  showWorkflowBadge?: boolean
}): React.ReactElement {
  const isVector = isSvgAsset(asset)
  const iconLike = asset.asset_type === 'icon' || isVector
  const paddingClass = compact ? 'p-3' : large ? 'p-8' : 'p-5'

  return (
    <div className={clsx(className, iconLike && 'bg-slate-950')}>
      {iconLike && (
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_center,rgba(229,166,71,0.18),rgba(15,23,42,0.2)_48%,rgba(2,6,23,0.86)_100%)]" />
      )}
      {/* biome-ignore lint/performance/noImgElement: Design assets may be SVGs from the local API; direct img keeps vector previews reliable. */}
      <img
        src={imageUrl ?? getDesignAssetImageUrl(projectId, asset.asset_id)}
        alt={asset.name}
        draggable={false}
        className={clsx(
          'relative h-full w-full',
          iconLike ? ['object-contain', paddingClass] : 'object-cover',
          isVector && 'drop-shadow-[0_0_18px_rgba(229,166,71,0.24)]',
        )}
      />
      {showWorkflowBadge && (
        <div className="absolute left-2 top-2 rounded-full bg-slate-950/70 px-2 py-1 text-2xs uppercase tracking-[0.18em] text-cyan-200">
          {asset.workflow}
        </div>
      )}
      {isVector && (
        <div className="absolute right-2 top-2 rounded-full bg-amber-500/15 px-2 py-1 text-2xs uppercase tracking-[0.18em] text-amber-100 ring-1 ring-amber-300/20">
          SVG
        </div>
      )}
    </div>
  )
}

function isSvgAsset(asset: DesignAsset): boolean {
  const format = metadataString(asset, 'format')
  const mimeType = metadataString(asset, 'mime_type')
  return (
    format === 'svg' ||
    mimeType === 'image/svg+xml' ||
    asset.file_path?.toLowerCase().endsWith('.svg') === true
  )
}

function metadataString(asset: DesignAsset, key: string): string {
  return metadataText(asset, key).toLowerCase()
}

function metadataText(asset: DesignAsset, key: string): string {
  const value = asset.metadata[key]
  return typeof value === 'string' ? value : ''
}

function AssetStatusActions({
  asset,
  isUpdating,
  onStatusChange,
}: {
  asset: DesignAsset
  isUpdating: boolean
  onStatusChange: (status: string) => void
}): React.ReactElement {
  const actions = [
    { status: 'approved', activeLabel: 'Approved', idleLabel: 'Approve' },
    { status: 'rejected', activeLabel: 'Rejected', idleLabel: 'Reject' },
    { status: 'archived', activeLabel: 'Archived', idleLabel: 'Archive' },
  ]

  return (
    <>
      {actions.map((action) => {
        const isActive = asset.status === action.status

        return (
          <button
            key={action.status}
            type="button"
            aria-pressed={isActive}
            onClick={() =>
              onStatusChange(nextAssetReviewStatus(asset.status, action.status))
            }
            disabled={isUpdating}
            className={statusActionClass(action.status, isActive)}
            title={isActive ? 'Click again to clear review status' : undefined}
          >
            {isActive ? action.activeLabel : action.idleLabel}
          </button>
        )
      })}
    </>
  )
}

function AssetRatingActions({
  asset,
  isRating,
  onRate,
}: {
  asset: DesignAsset
  isRating: boolean
  onRate: (rating: number) => void
}): React.ReactElement {
  return (
    <StarRating
      average={asset.rating_average}
      count={asset.rating_count}
      userRating={asset.user_rating}
      disabled={isRating}
      onRate={onRate}
    />
  )
}

export function nextAssetReviewStatus(
  currentStatus: string,
  requestedStatus: string,
): string {
  return currentStatus === requestedStatus ? 'generated' : requestedStatus
}

function statusActionClass(status: string, isActive: boolean): string {
  if (!isActive) {
    return 'btn-secondary disabled:opacity-50'
  }

  if (status === 'approved') {
    return 'rounded-lg border border-emerald-400/60 bg-emerald-500/15 px-3 py-2 text-sm font-medium text-emerald-100 disabled:opacity-100'
  }

  if (status === 'rejected') {
    return 'rounded-lg border border-rose-400/60 bg-rose-500/15 px-3 py-2 text-sm font-medium text-rose-100 disabled:opacity-100'
  }

  return 'rounded-lg border border-amber-400/60 bg-amber-500/15 px-3 py-2 text-sm font-medium text-amber-100 disabled:opacity-100'
}

function AssetInspector({
  asset,
  projectId,
  isExporting,
  isUpdating,
  isRating,
  readOnly,
  imageUrl,
  onClose,
  onDelete,
  onExport,
  onPreview,
  onStatusChange,
  onRate,
}: {
  asset: DesignAsset | null
  projectId: string
  isExporting: boolean
  isUpdating: boolean
  isRating: boolean
  readOnly: boolean
  imageUrl?: string
  onClose: () => void
  onDelete: () => void
  onExport: () => void
  onPreview: () => void
  onStatusChange: (status: string) => void
  onRate: (rating: number) => void
}): React.ReactElement {
  const { data: exports } = useQuery({
    queryKey: ['design-asset-exports', projectId, asset?.asset_id],
    queryFn: () => fetchDesignAssetExports(projectId, asset!.asset_id),
    enabled: asset != null && !readOnly,
  })

  if (!asset) {
    return (
      <aside className="card p-5">
        <p className="text-xs uppercase tracking-[0.22em] text-cyan-300">
          Inspector
        </p>
        <h3 className="mt-2 text-lg font-semibold text-slate-100">
          Select an asset
        </h3>
        <p className="mt-3 text-sm text-slate-400">
          Review prompts, tags, export records, and production metadata from a
          persistent right-hand inspector.
        </p>
      </aside>
    )
  }

  return (
    <aside className="card overflow-auto p-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-[0.22em] text-cyan-300">
            {asset.workflow}
          </p>
          <h3 className="mt-1 text-xl font-semibold text-slate-100">
            {asset.name}
          </h3>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          className="text-slate-500 hover:text-slate-100"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <AssetPreview
        asset={asset}
        projectId={projectId}
        imageUrl={imageUrl}
        large
        className="relative mt-4 aspect-video overflow-hidden rounded-2xl bg-slate-900"
      />

      <button
        type="button"
        onClick={onPreview}
        className="btn-secondary mt-3 flex w-full items-center justify-center gap-2"
      >
        <Maximize2 className="h-4 w-4" />
        Fullscreen Preview
      </button>

      {asset.description && (
        <p className="mt-4 text-sm text-slate-300">{asset.description}</p>
      )}

      <div className="mt-5 grid grid-cols-2 gap-3 text-sm">
        <InspectorField
          label="Type"
          value={asset.asset_type.replace('_', ' ')}
        />
        <InspectorField label="Status" value={asset.status} />
        <InspectorField
          label="Average rating"
          value={`${asset.rating_average.toFixed(1)} / 5`}
        />
        <InspectorField
          label="Resolution"
          value={`${asset.width}x${asset.height}`}
        />
        <InspectorField label="Background" value={asset.background} />
      </div>

      <div className="mt-5">
        <p className="text-xs uppercase tracking-[0.18em] text-slate-500">
          Rating
        </p>
        <AssetRatingActions asset={asset} isRating={isRating} onRate={onRate} />
      </div>

      {asset.tags.length > 0 && (
        <div className="mt-5">
          <p className="text-xs uppercase tracking-[0.18em] text-slate-500">
            Tags
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            {asset.tags.map((tag) => (
              <span
                key={tag}
                className="rounded-full bg-cyan-500/10 px-2 py-1 text-xs text-cyan-200"
              >
                {tag}
              </span>
            ))}
          </div>
        </div>
      )}

      <div className="mt-5">
        <p className="text-xs uppercase tracking-[0.18em] text-slate-500">
          Prompt
        </p>
        <div className="mt-2 rounded-xl bg-slate-900 p-3 text-sm text-slate-300 whitespace-pre-wrap">
          {asset.prompt}
        </div>
      </div>

      {asset.asset_type === 'sprite_sheet' && (
        <div className="mt-5 rounded-xl bg-slate-900 p-3 text-sm text-slate-300">
          <p>
            Grid: {asset.sheet_columns} x {asset.sheet_rows}
          </p>
          <p>
            Frame: {asset.frame_width} x {asset.frame_height}
          </p>
          <p>
            Animations: {asset.animation_labels.join(', ') || 'Not labeled'}
          </p>
        </div>
      )}

      <div className="mt-5 flex flex-wrap gap-2">
        {!readOnly && (
          <>
            <AssetStatusActions
              asset={asset}
              isUpdating={isUpdating}
              onStatusChange={onStatusChange}
            />
            {asset.asset_type === 'sprite_sheet' && (
              <button
                type="button"
                onClick={onExport}
                disabled={isExporting}
                className="btn-secondary flex items-center gap-2"
              >
                <Download className="h-4 w-4" />
                Export Frames
              </button>
            )}
            <button
              type="button"
              onClick={onDelete}
              className="btn-secondary text-rose-300"
            >
              Delete
            </button>
          </>
        )}
      </div>

      {!readOnly && (
        <div className="mt-6">
          <p className="text-xs uppercase tracking-[0.18em] text-slate-500">
            Exports
          </p>
          <div className="mt-2 space-y-2">
            {(exports ?? []).length === 0 && (
              <div className="rounded-xl border border-dashed border-slate-700 p-3 text-sm text-slate-500">
                No exports generated yet.
              </div>
            )}
            {(exports ?? []).map((assetExport: DesignAssetExport) => (
              <div
                key={assetExport.export_id}
                className="rounded-xl bg-slate-900 p-3 text-sm"
              >
                <div className="flex items-center justify-between gap-3">
                  <span className="text-slate-100">
                    {assetExport.export_type}
                  </span>
                  <span className="text-slate-500">
                    {assetExport.file_path}
                  </span>
                </div>
                {assetExport.manifest_path && (
                  <p className="mt-1 text-xs text-slate-500">
                    Manifest: {assetExport.manifest_path}
                  </p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </aside>
  )
}

function AssetDetailModal({
  asset,
  isExporting,
  isUpdating,
  isRating,
  readOnly,
  imageUrl,
  navigation,
  onClose,
  onDelete,
  onExport,
  onStatusChange,
  onRate,
  onCommentsChanged,
}: {
  asset: DesignAsset
  isExporting: boolean
  isUpdating: boolean
  isRating: boolean
  readOnly: boolean
  imageUrl: string
  navigation?: AssetModalNavigation
  onClose: () => void
  onDelete: () => void
  onExport: () => void
  onStatusChange: (status: string) => void
  onRate: (rating: number) => void
  onCommentsChanged: () => void
}): React.ReactElement {
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
      if (event.key === 'ArrowLeft' && navigation?.canGoPrevious) {
        event.preventDefault()
        navigation.onPrevious()
      }
      if (event.key === 'ArrowRight' && navigation?.canGoNext) {
        event.preventDefault()
        navigation.onNext()
      }
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [navigation, onClose])

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div
        className="absolute inset-0 bg-slate-950/90 backdrop-blur-sm"
        onClick={onClose}
        role="presentation"
      />

      <div className="relative mx-2 flex h-[94vh] w-[98vw] flex-col overflow-hidden rounded-xl bg-slate-900">
        <div className="flex flex-shrink-0 items-center justify-between gap-4 border-b border-slate-800 px-5 py-4">
          <div className="min-w-0">
            <p className="text-xs uppercase tracking-[0.22em] text-cyan-300">
              {asset.workflow}
            </p>
            <h2 className="mt-1 truncate text-lg font-semibold text-slate-100">
              {asset.name}
            </h2>
          </div>
          <div className="flex items-center gap-2">
            {navigation && (
              <>
                <button
                  type="button"
                  onClick={navigation.onPrevious}
                  disabled={!navigation.canGoPrevious}
                  aria-label="Previous asset"
                  className="flex h-10 w-10 items-center justify-center rounded-lg border border-slate-700 text-slate-300 transition hover:border-slate-500 hover:text-slate-100 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  <ChevronLeft className="h-5 w-5" />
                </button>
                <span className="min-w-16 text-center text-xs text-slate-400">
                  {navigation.currentIndex} of {navigation.totalCount}
                </span>
                <button
                  type="button"
                  onClick={navigation.onNext}
                  disabled={!navigation.canGoNext}
                  aria-label="Next asset"
                  className="flex h-10 w-10 items-center justify-center rounded-lg border border-slate-700 text-slate-300 transition hover:border-slate-500 hover:text-slate-100 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  <ChevronRight className="h-5 w-5" />
                </button>
              </>
            )}
            <a
              href={imageUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="btn-secondary flex items-center gap-2"
            >
              <ExternalLink className="h-4 w-4" />
              Open
            </a>
            <a
              href={imageUrl}
              download={`${asset.asset_id}.${isSvgAsset(asset) ? 'svg' : 'png'}`}
              className="btn-secondary flex items-center gap-2"
            >
              <Download className="h-4 w-4" />
              Download
            </a>
            <button
              type="button"
              onClick={onClose}
              aria-label="Close fullscreen preview"
              className="rounded-lg p-2 text-slate-400 transition-colors hover:bg-slate-800 hover:text-slate-100"
            >
              <X className="h-5 w-5" />
            </button>
          </div>
        </div>

        <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
          <div className="relative flex min-h-0 flex-1 items-center justify-center bg-slate-950 p-4">
            {navigation?.canGoPrevious && (
              <button
                type="button"
                onClick={navigation.onPrevious}
                aria-label="Previous asset"
                className="absolute left-4 top-1/2 z-10 flex h-14 w-14 -translate-y-1/2 items-center justify-center rounded-full border border-slate-700 bg-slate-950/70 text-slate-200 backdrop-blur transition hover:border-cyan-400/60 hover:text-cyan-100"
              >
                <ChevronLeft className="h-7 w-7" />
              </button>
            )}
            {/* biome-ignore lint/performance/noImgElement: Asset previews can be user-imported SVG/PNG files; direct img preserves native rendering. */}
            <img
              src={imageUrl}
              alt={asset.name}
              className="max-h-full max-w-full object-contain"
              draggable={false}
            />
            {navigation?.canGoNext && (
              <button
                type="button"
                onClick={navigation.onNext}
                aria-label="Next asset"
                className="absolute right-4 top-1/2 z-10 flex h-14 w-14 -translate-y-1/2 items-center justify-center rounded-full border border-slate-700 bg-slate-950/70 text-slate-200 backdrop-blur transition hover:border-cyan-400/60 hover:text-cyan-100"
              >
                <ChevronRight className="h-7 w-7" />
              </button>
            )}
          </div>

          <aside className="w-full flex-shrink-0 overflow-auto border-t border-slate-800 p-5 lg:w-96 lg:border-l lg:border-t-0">
            <div className="grid grid-cols-2 gap-3 text-sm">
              <InspectorField
                label="Type"
                value={asset.asset_type.replace('_', ' ')}
              />
              <InspectorField label="Status" value={asset.status} />
              <InspectorField
                label="Average rating"
                value={`${asset.rating_average.toFixed(1)} / 5`}
              />
              <InspectorField
                label="Resolution"
                value={`${asset.width}x${asset.height}`}
              />
              <InspectorField label="Background" value={asset.background} />
            </div>

            <div className="mt-5">
              <p className="text-xs uppercase tracking-[0.18em] text-slate-500">
                Rating
              </p>
              <AssetRatingActions
                asset={asset}
                isRating={isRating}
                onRate={onRate}
              />
            </div>

            <ArtifactComments
              queryKey={[
                'design-asset-comments',
                readOnly ? 'viewer' : 'owner',
                asset.project_id,
                asset.asset_id,
              ]}
              fetchComments={() =>
                (readOnly
                  ? fetchViewerDesignAssetComments
                  : fetchDesignAssetComments)(asset.project_id, asset.asset_id)
              }
              addComment={(body) =>
                (readOnly
                  ? addViewerDesignAssetComment
                  : addDesignAssetComment)(
                  asset.project_id,
                  asset.asset_id,
                  body,
                )
              }
              updateComment={(commentId, body) =>
                (readOnly
                  ? updateViewerDesignAssetComment
                  : updateDesignAssetComment)(
                  asset.project_id,
                  asset.asset_id,
                  commentId,
                  body,
                )
              }
              deleteComment={(commentId) =>
                (readOnly
                  ? deleteViewerDesignAssetComment
                  : deleteDesignAssetComment)(
                  asset.project_id,
                  asset.asset_id,
                  commentId,
                )
              }
              onChanged={onCommentsChanged}
            />

            {asset.tags.length > 0 && (
              <div className="mt-5">
                <p className="text-xs uppercase tracking-[0.18em] text-slate-500">
                  Tags
                </p>
                <div className="mt-2 flex flex-wrap gap-2">
                  {asset.tags.map((tag) => (
                    <span
                      key={tag}
                      className="rounded-full bg-cyan-500/10 px-2 py-1 text-xs text-cyan-200"
                    >
                      {tag}
                    </span>
                  ))}
                </div>
              </div>
            )}

            <div className="mt-5">
              <p className="text-xs uppercase tracking-[0.18em] text-slate-500">
                Prompt
              </p>
              <div className="mt-2 rounded-xl bg-slate-950 p-3 text-sm text-slate-300 whitespace-pre-wrap">
                {asset.prompt}
              </div>
            </div>

            {asset.asset_type === 'sprite_sheet' && (
              <div className="mt-5 rounded-xl bg-slate-950 p-3 text-sm text-slate-300">
                <p>
                  Grid: {asset.sheet_columns} x {asset.sheet_rows}
                </p>
                <p>
                  Frame: {asset.frame_width} x {asset.frame_height}
                </p>
                <p>
                  Animations:{' '}
                  {asset.animation_labels.join(', ') || 'Not labeled'}
                </p>
              </div>
            )}

            <div className="mt-5 flex flex-wrap gap-2">
              {!readOnly && (
                <>
                  <AssetStatusActions
                    asset={asset}
                    isUpdating={isUpdating}
                    onStatusChange={onStatusChange}
                  />
                  {asset.asset_type === 'sprite_sheet' && (
                    <button
                      type="button"
                      onClick={onExport}
                      disabled={isExporting}
                      className="btn-secondary flex items-center gap-2"
                    >
                      <Download className="h-4 w-4" />
                      Export Frames
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={onDelete}
                    className="btn-secondary text-rose-300"
                  >
                    Delete
                  </button>
                </>
              )}
            </div>
          </aside>
        </div>
      </div>
    </div>
  )
}

function InspectorField({
  label,
  value,
}: {
  label: string
  value: string
}): React.ReactElement {
  return (
    <div className="rounded-xl bg-slate-900 p-3">
      <p className="text-xs uppercase tracking-[0.18em] text-slate-500">
        {label}
      </p>
      <p className="mt-1 text-slate-100 capitalize">{value}</p>
    </div>
  )
}
