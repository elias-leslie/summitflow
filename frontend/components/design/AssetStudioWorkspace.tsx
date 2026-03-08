'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Download, Image as ImageIcon, Layers3, Package, Tags, X } from 'lucide-react'
import Image from 'next/image'
import { useState } from 'react'
import { ConfirmDeleteDialog } from '@/components/shared/ConfirmDeleteDialog'
import {
  deleteDesignAsset,
  exportSpriteFrames,
  fetchDesignAssetExports,
  fetchDesignAssetStats,
  fetchDesignAssets,
  getDesignAssetImageUrl,
  type DesignAsset,
  type DesignAssetExport,
  updateDesignAssetStatus,
} from '@/lib/api/design-assets'
import { DesignHeader, type ViewMode } from './DesignHeader'
import { GenerateAssetDialog } from './GenerateAssetDialog'
import { EmptyState, ErrorState, LoadingState } from './MockupStates'

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

interface AssetStudioWorkspaceProps {
  projectId: string
}

export function AssetStudioWorkspace({
  projectId,
}: AssetStudioWorkspaceProps): React.ReactElement {
  const [viewMode, setViewMode] = useState<ViewMode>('grid')
  const [statusFilter, setStatusFilter] = useState<AssetStatusFilter>('all')
  const [typeFilter, setTypeFilter] = useState<AssetTypeFilter>('all')
  const [workflowFilter, setWorkflowFilter] = useState<WorkflowFilter>('all')
  const [searchQuery, setSearchQuery] = useState('')
  const [page, setPage] = useState(0)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [selectedAsset, setSelectedAsset] = useState<DesignAsset | null>(null)
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)
  const pageSize = 24
  const queryClient = useQueryClient()

  const {
    data: assetData,
    isLoading,
    error,
    refetch,
  } = useQuery({
    queryKey: [
      'design-assets',
      projectId,
      statusFilter,
      typeFilter,
      workflowFilter,
      searchQuery,
      page,
    ],
    queryFn: () =>
      fetchDesignAssets(projectId, {
        limit: pageSize,
        offset: page * pageSize,
        status: statusFilter === 'all' ? undefined : statusFilter,
        asset_type: typeFilter === 'all' ? undefined : typeFilter,
        workflow: workflowFilter === 'all' ? undefined : workflowFilter,
        search: searchQuery || undefined,
      }),
  })

  const { data: stats } = useQuery({
    queryKey: ['design-assets-stats', projectId],
    queryFn: () => fetchDesignAssetStats(projectId),
  })

  const statusMutation = useMutation({
    mutationFn: async ({
      assetId,
      status,
    }: {
      assetId: string
      status: string
    }) => updateDesignAssetStatus(projectId, assetId, status, 'codex'),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['design-assets', projectId] })
      queryClient.invalidateQueries({ queryKey: ['design-assets-stats', projectId] })
      refetch()
    },
  })

  const deleteMutation = useMutation({
    mutationFn: async (assetId: string) => deleteDesignAsset(projectId, assetId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['design-assets', projectId] })
      queryClient.invalidateQueries({ queryKey: ['design-assets-stats', projectId] })
      setShowDeleteConfirm(false)
      setSelectedAsset(null)
    },
  })

  const exportMutation = useMutation({
    mutationFn: async (assetId: string) => exportSpriteFrames(projectId, assetId),
    onSuccess: () => {
      if (selectedAsset) {
        queryClient.invalidateQueries({
          queryKey: ['design-asset-exports', projectId, selectedAsset.asset_id],
        })
      }
      queryClient.invalidateQueries({ queryKey: ['design-assets', projectId] })
      queryClient.invalidateQueries({ queryKey: ['design-assets-stats', projectId] })
    },
  })

  const assets = assetData?.items ?? []
  const totalCount = assetData?.total ?? 0

  return (
    <div className="flex h-full flex-col min-w-0">
      <DesignHeader
        title="Asset Studio"
        subtitle="Generate production-oriented assets, review variants, and export sprite sheets into frame packs."
        totalLabel={stats?.total !== undefined ? `${stats.total} assets` : undefined}
        primaryActionLabel="Generate Assets"
        viewMode={viewMode}
        selectMode={false}
        hasItems={assets.length > 0}
        onViewModeChange={setViewMode}
        onSelectModeToggle={() => undefined}
        onCancelSelectMode={() => undefined}
        onPrimaryAction={() => setDialogOpen(true)}
      />

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

      <div className="mb-6 grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
        <div className="card grid grid-cols-1 gap-3 p-4 lg:grid-cols-2 xl:grid-cols-5">
          <input
            value={searchQuery}
            onChange={(event) => {
              setSearchQuery(event.target.value)
              setPage(0)
            }}
            placeholder="Search generated assets..."
            className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-white xl:col-span-2"
          />
          <select
            value={statusFilter}
            onChange={(event) => {
              setStatusFilter(event.target.value as AssetStatusFilter)
              setPage(0)
            }}
            className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-white"
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
            className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-white"
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
            className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-white"
          >
            <option value="all">All Workflows</option>
            <option value="concept">Concept</option>
            <option value="production">Production</option>
            <option value="marketing">Marketing</option>
            <option value="ui">UI</option>
          </select>
        </div>

        <aside className="card p-4">
          <p className="text-xs uppercase tracking-[0.22em] text-cyan-300">Production Playbook</p>
          <h3 className="mt-2 text-lg font-semibold text-white">Asset Direction</h3>
          <div className="mt-4 space-y-4 text-sm text-slate-300">
            <p>Use transparent backgrounds for sprites, icons, portraits, and UI textures.</p>
            <p>Use `production` workflow for in-game art, `marketing` for promo mockups, and `ui` for product-facing visuals.</p>
            <p>Sprite sheets become exportable once rows, columns, frame sizes, and animation labels are defined.</p>
          </div>
        </aside>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="min-h-0">
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
              description="Generate sprites, environments, icon sets, or sprite sheets and review them in a production-focused asset workspace."
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
                  <button
                    key={asset.asset_id}
                    onClick={() => setSelectedAsset(asset)}
                    className={`card overflow-hidden text-left transition hover:ring-1 hover:ring-cyan-400/30 ${
                      viewMode === 'list' ? 'flex items-center gap-4 p-3' : ''
                    }`}
                  >
                    <div
                      className={`relative overflow-hidden rounded-xl bg-slate-900 ${
                        viewMode === 'grid'
                          ? 'aspect-video'
                          : 'h-24 w-40 flex-shrink-0'
                      }`}
                    >
                      <Image
                        src={getDesignAssetImageUrl(projectId, asset.asset_id)}
                        alt={asset.name}
                        fill
                        className="object-cover"
                        unoptimized
                      />
                      <div className="absolute left-2 top-2 rounded-full bg-black/65 px-2 py-1 text-[11px] uppercase tracking-[0.18em] text-cyan-200">
                        {asset.workflow}
                      </div>
                    </div>
                    <div className={viewMode === 'grid' ? 'p-4' : 'min-w-0'}>
                      <div className="flex items-center justify-between gap-3">
                        <h3 className="truncate text-white font-medium">{asset.name}</h3>
                        <span className="text-[11px] uppercase tracking-[0.18em] text-slate-500">
                          {asset.asset_type.replace('_', ' ')}
                        </span>
                      </div>
                      {asset.description && (
                        <p className="mt-2 line-clamp-2 text-sm text-slate-400">
                          {asset.description}
                        </p>
                      )}
                      <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-500">
                        <span>{asset.width}x{asset.height}</span>
                        <span>{asset.model ?? 'default model'}</span>
                        <span className="capitalize">{asset.status}</span>
                      </div>
                    </div>
                  </button>
                ))}
              </div>

              {totalCount > pageSize && (
                <div className="mt-6 flex items-center justify-center gap-4 pb-4">
                  <button
                    onClick={() => setPage(Math.max(0, page - 1))}
                    disabled={page === 0}
                    className="btn-secondary disabled:opacity-50"
                  >
                    Previous
                  </button>
                  <span className="text-slate-400">
                    Page {page + 1} of {Math.ceil(totalCount / pageSize)}
                  </span>
                  <button
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
        </div>

        <AssetInspector
          asset={selectedAsset}
          projectId={projectId}
          isExporting={exportMutation.isPending}
          isUpdating={statusMutation.isPending}
          onClose={() => setSelectedAsset(null)}
          onDelete={() => setShowDeleteConfirm(true)}
          onExport={() => selectedAsset && exportMutation.mutate(selectedAsset.asset_id)}
          onStatusChange={(status) =>
            selectedAsset &&
            statusMutation.mutate({ assetId: selectedAsset.asset_id, status })
          }
        />
      </div>

      <GenerateAssetDialog
        projectId={projectId}
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        onGenerated={async (createdAssets) => {
          queryClient.invalidateQueries({ queryKey: ['design-assets', projectId] })
          queryClient.invalidateQueries({ queryKey: ['design-assets-stats', projectId] })
          if (createdAssets[0]) setSelectedAsset(createdAssets[0])
        }}
      />

      {selectedAsset && showDeleteConfirm && (
        <ConfirmDeleteDialog
          entityType="mockup"
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
        <div className="text-lg font-semibold text-white">{value}</div>
        <div className="text-xs uppercase tracking-[0.18em] text-slate-500">{label}</div>
      </div>
    </div>
  )
}

function AssetInspector({
  asset,
  projectId,
  isExporting,
  isUpdating,
  onClose,
  onDelete,
  onExport,
  onStatusChange,
}: {
  asset: DesignAsset | null
  projectId: string
  isExporting: boolean
  isUpdating: boolean
  onClose: () => void
  onDelete: () => void
  onExport: () => void
  onStatusChange: (status: string) => void
}): React.ReactElement {
  const { data: exports } = useQuery({
    queryKey: ['design-asset-exports', projectId, asset?.asset_id],
    queryFn: () => fetchDesignAssetExports(projectId, asset!.asset_id),
    enabled: asset != null,
  })

  if (!asset) {
    return (
      <aside className="card p-5">
        <p className="text-xs uppercase tracking-[0.22em] text-cyan-300">Inspector</p>
        <h3 className="mt-2 text-lg font-semibold text-white">Select an asset</h3>
        <p className="mt-3 text-sm text-slate-400">
          Review prompts, tags, export records, and production metadata from a persistent right-hand inspector.
        </p>
      </aside>
    )
  }

  return (
    <aside className="card overflow-auto p-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-[0.22em] text-cyan-300">{asset.workflow}</p>
          <h3 className="mt-1 text-xl font-semibold text-white">{asset.name}</h3>
        </div>
        <button onClick={onClose} className="text-slate-500 hover:text-white">
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="relative mt-4 aspect-video overflow-hidden rounded-2xl bg-slate-900">
        <Image
          src={getDesignAssetImageUrl(projectId, asset.asset_id)}
          alt={asset.name}
          fill
          className="object-cover"
          unoptimized
        />
      </div>

      {asset.description && <p className="mt-4 text-sm text-slate-300">{asset.description}</p>}

      <div className="mt-5 grid grid-cols-2 gap-3 text-sm">
        <InspectorField label="Type" value={asset.asset_type.replace('_', ' ')} />
        <InspectorField label="Status" value={asset.status} />
        <InspectorField label="Resolution" value={`${asset.width}x${asset.height}`} />
        <InspectorField label="Background" value={asset.background} />
      </div>

      {asset.tags.length > 0 && (
        <div className="mt-5">
          <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Tags</p>
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
        <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Prompt</p>
        <div className="mt-2 rounded-xl bg-slate-900 p-3 text-sm text-slate-300 whitespace-pre-wrap">
          {asset.prompt}
        </div>
      </div>

      {asset.asset_type === 'sprite_sheet' && (
        <div className="mt-5 rounded-xl bg-slate-900 p-3 text-sm text-slate-300">
          <p>Grid: {asset.sheet_columns} x {asset.sheet_rows}</p>
          <p>Frame: {asset.frame_width} x {asset.frame_height}</p>
          <p>Animations: {asset.animation_labels.join(', ') || 'Not labeled'}</p>
        </div>
      )}

      <div className="mt-5 flex flex-wrap gap-2">
        <button onClick={() => onStatusChange('approved')} disabled={isUpdating} className="btn-primary">
          Approve
        </button>
        <button onClick={() => onStatusChange('rejected')} disabled={isUpdating} className="btn-secondary">
          Reject
        </button>
        <button onClick={() => onStatusChange('archived')} disabled={isUpdating} className="btn-secondary">
          Archive
        </button>
        {asset.asset_type === 'sprite_sheet' && (
          <button
            onClick={onExport}
            disabled={isExporting}
            className="btn-secondary flex items-center gap-2"
          >
            <Download className="h-4 w-4" />
            Export Frames
          </button>
        )}
        <button onClick={onDelete} className="btn-secondary text-rose-300">
          Delete
        </button>
      </div>

      <div className="mt-6">
        <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Exports</p>
        <div className="mt-2 space-y-2">
          {(exports ?? []).length === 0 && (
            <div className="rounded-xl border border-dashed border-slate-700 p-3 text-sm text-slate-500">
              No exports generated yet.
            </div>
          )}
          {(exports ?? []).map((assetExport: DesignAssetExport) => (
            <div key={assetExport.export_id} className="rounded-xl bg-slate-900 p-3 text-sm">
              <div className="flex items-center justify-between gap-3">
                <span className="text-white">{assetExport.export_type}</span>
                <span className="text-slate-500">{assetExport.file_path}</span>
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
    </aside>
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
      <p className="text-xs uppercase tracking-[0.18em] text-slate-500">{label}</p>
      <p className="mt-1 text-white capitalize">{value}</p>
    </div>
  )
}
