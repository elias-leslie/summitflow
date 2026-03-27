'use client'

import clsx from 'clsx'
import { AlertCircle, ArrowLeft, FolderPlus } from 'lucide-react'
import Link from 'next/link'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { DEFAULT_HEALTH_ENDPOINT } from '@/lib/project-registration'
import { ROUTE_HOME } from './constants'
import { AgentHubSection } from './AgentHubSection'
import { ProjectPreviewPanel } from './ProjectPreviewPanel'
import { useNewProjectForm } from './useNewProjectForm'

export function NewProjectClient() {
  const { fields, agentHub, errors, isPending, preview, handlers } = useNewProjectForm()
  const { name, projectId, baseUrl, healthEndpoint, rootPath } = fields
  const { syncAgentHubPermission, permissionTier, autoExecEnabled } = agentHub
  const {
    handleNameChange,
    handleProjectIdChange,
    handleBaseUrlChange,
    handleHealthEndpointChange,
    handleRootPathChange,
    handleSubmit,
    setSyncAgentHubPermission,
    setPermissionTier,
    setAutoExecEnabled,
  } = handlers

  return (
    <div className="mx-auto max-w-4xl space-y-4 px-4 py-4 md:px-5 lg:px-6">
      <header className="animate-in">
        <Link
          href={ROUTE_HOME}
          className="mb-3 inline-flex items-center gap-1.5 rounded-full border border-slate-800/60 bg-slate-950/60 px-2.5 py-1 text-xs text-slate-400 transition-colors hover:border-phosphor-500/30 hover:text-phosphor-300"
        >
          <ArrowLeft className="h-3 w-3" />
          Back
        </Link>

        <div className="flex items-center gap-3">
          <FolderPlus className="h-5 w-5 text-phosphor-400" />
          <div>
            <h1 className="display text-xl font-bold text-slate-100 tracking-tight">
              Create Project
            </h1>
            <p className="text-sm text-slate-400">
              Register the app, then SummitFlow tracks health, scans, and work
            </p>
          </div>
        </div>
      </header>

      <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_260px]">
        <form onSubmit={handleSubmit} className="card space-y-4 p-4">
          {errors.submit && (
            <div className="flex items-center gap-2 rounded-lg border border-rose-500/20 bg-rose-500/10 p-3 text-sm text-rose-400">
              <AlertCircle className="h-4 w-4 shrink-0" />
              {errors.submit}
            </div>
          )}

          <div className="space-y-2">
            <Label htmlFor="name">Project Name *</Label>
            <Input
              id="name"
              value={name}
              onChange={(e) => handleNameChange(e.target.value)}
              placeholder="My Awesome Project"
              aria-invalid={Boolean(errors.name)}
              className={errors.name ? 'border-rose-500/50' : ''}
            />
            {errors.name && <p className="text-xs text-rose-400">{errors.name}</p>}
          </div>

          <div className="space-y-2">
            <Label htmlFor="projectId">Project ID *</Label>
            <Input
              id="projectId"
              value={projectId}
              onChange={(e) => handleProjectIdChange(e.target.value)}
              placeholder="my-awesome-project"
              aria-invalid={Boolean(errors.projectId)}
              className={clsx('mono', errors.projectId && 'border-rose-500/50')}
            />
            <p className="text-xs text-slate-500">
              Stable slug used for APIs, tasks, and navigation. Auto-generated from the name until you override it.
            </p>
            {errors.projectId && (
              <p className="text-xs text-rose-400">{errors.projectId}</p>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="baseUrl">Base URL *</Label>
            <Input
              id="baseUrl"
              type="url"
              value={baseUrl}
              onChange={(e) => handleBaseUrlChange(e.target.value)}
              placeholder="https://example.com"
              aria-invalid={Boolean(errors.baseUrl)}
              className={errors.baseUrl ? 'border-rose-500/50' : ''}
            />
            <p className="text-xs text-slate-500">
              Root URL used for health checks and operator links. SummitFlow-hosted projects auto-fill to `https://&lt;project-id&gt;.summitflow.dev`.
            </p>
            {errors.baseUrl && (
              <p className="text-xs text-rose-400">{errors.baseUrl}</p>
            )}
          </div>

          <div className="chrome-line my-1" />

          <div className="space-y-2">
            <Label htmlFor="healthEndpoint">Health Endpoint</Label>
            <Input
              id="healthEndpoint"
              value={healthEndpoint}
              onChange={(e) => handleHealthEndpointChange(e.target.value)}
              placeholder={DEFAULT_HEALTH_ENDPOINT}
              aria-invalid={Boolean(errors.healthEndpoint)}
              className={clsx('mono', errors.healthEndpoint && 'border-rose-500/50')}
            />
            <p className="text-xs text-slate-500">
              Relative path or full URL for service checks. Leave the default unless the app exposes a different route.
            </p>
            {errors.healthEndpoint && (
              <p className="text-xs text-rose-400">{errors.healthEndpoint}</p>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="rootPath">Root Path</Label>
            <Input
              id="rootPath"
              value={rootPath}
              onChange={(e) => handleRootPathChange(e.target.value)}
              placeholder="/home/user/projects/my-project"
              aria-invalid={Boolean(errors.rootPath)}
              className={clsx('mono', errors.rootPath && 'border-rose-500/50')}
            />
            <p className="text-xs text-slate-500">
              Strongly recommended. SummitFlow-hosted projects auto-fill to `/srv/workspaces/projects/&lt;project-id&gt;`.
            </p>
            {errors.rootPath && (
              <p className="text-xs text-rose-400">{errors.rootPath}</p>
            )}
          </div>

          <div className="chrome-line my-1" />

          <AgentHubSection
            syncAgentHubPermission={syncAgentHubPermission}
            permissionTier={permissionTier}
            autoExecEnabled={autoExecEnabled}
            onSyncChange={setSyncAgentHubPermission}
            onTierChange={setPermissionTier}
            onAutoExecChange={setAutoExecEnabled}
          />

          <div className="flex items-center gap-3 pt-2">
            <button
              type="submit"
              disabled={isPending}
              className="btn-primary flex items-center gap-2 text-sm"
            >
              {isPending ? (
                <>
                  <div className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
                  Creating...
                </>
              ) : (
                <>
                  <FolderPlus className="h-4 w-4" />
                  Create Project
                </>
              )}
            </button>
            <Link href={ROUTE_HOME} className="btn-secondary text-sm">
              Cancel
            </Link>
          </div>
        </form>

        <ProjectPreviewPanel
          projectId={projectId}
          healthPreview={preview.healthPreview}
          normalizedRootPath={preview.normalizedRootPath}
          syncAgentHubPermission={syncAgentHubPermission}
          permissionTier={permissionTier}
          autoExecEnabled={autoExecEnabled}
        />
      </div>
    </div>
  )
}
