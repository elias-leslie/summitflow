'use client'

import clsx from 'clsx'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { AlertCircle, ArrowLeft, FolderPlus, FolderTree, HeartPulse } from 'lucide-react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useState } from 'react'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { createProject } from '@/lib/api'
import {
  buildHealthPreview,
  DEFAULT_HEALTH_ENDPOINT,
  normalizeProjectFormValues,
  normalizeProjectId,
  normalizeRootPath,
  type ProjectFormErrors,
  validateProjectForm,
} from '@/lib/project-registration'

type FormErrors = ProjectFormErrors & { submit?: string }
type ErrorField = keyof FormErrors

export function NewProjectClient() {
  const router = useRouter()
  const queryClient = useQueryClient()

  const [name, setName] = useState('')
  const [projectId, setProjectId] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [healthEndpoint, setHealthEndpoint] = useState(DEFAULT_HEALTH_ENDPOINT)
  const [rootPath, setRootPath] = useState('')
  const [syncAgentHubPermission, setSyncAgentHubPermission] = useState(true)
  const [permissionTier, setPermissionTier] = useState('read')
  const [autoExecEnabled, setAutoExecEnabled] = useState(false)
  const [errors, setErrors] = useState<FormErrors>({})

  const mutation = useMutation({
    mutationFn: createProject,
    onSuccess: (project) => {
      queryClient.invalidateQueries({ queryKey: ['projects'] })
      queryClient.invalidateQueries({ queryKey: ['projects-with-stats'] })
      router.push(`/projects/${project.id}`)
    },
    onError: (error: Error) => {
      setErrors({ submit: error.message })
    },
  })

  const clearError = (field: ErrorField) => {
    setErrors((current) => {
      if (!(field in current) && !('submit' in current)) {
        return current
      }

      const next = { ...current }
      delete next[field]
      delete next.submit
      return next
    })
  }

  const handleNameChange = (value: string) => {
    clearError('name')
    setName(value)
    if (!projectId || projectId === normalizeProjectId(name)) {
      setProjectId(normalizeProjectId(value))
    }
  }

  const handleProjectIdChange = (value: string) => {
    clearError('projectId')
    setProjectId(normalizeProjectId(value))
  }

  const handleBaseUrlChange = (value: string) => {
    clearError('baseUrl')
    setBaseUrl(value)
  }

  const handleHealthEndpointChange = (value: string) => {
    clearError('healthEndpoint')
    setHealthEndpoint(value)
  }

  const handleRootPathChange = (value: string) => {
    clearError('rootPath')
    setRootPath(value)
  }

  const validate = (): boolean => {
    const newErrors = validateProjectForm({
      name,
      projectId,
      baseUrl,
      healthEndpoint,
      rootPath,
    })
    setErrors(newErrors)

    if (Object.keys(newErrors).length === 0) {
      const normalized = normalizeProjectFormValues({
        name,
        projectId,
        baseUrl,
        healthEndpoint,
        rootPath,
      })
      setProjectId(normalized.projectId ?? '')
      setBaseUrl(normalized.baseUrl)
      setHealthEndpoint(normalized.healthEndpoint)
      setRootPath(normalized.rootPath)
    }

    return Object.keys(newErrors).length === 0
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!validate()) return

    const normalized = normalizeProjectFormValues({
      name,
      projectId,
      baseUrl,
      healthEndpoint,
      rootPath,
    })

    mutation.mutate({
      id: normalized.projectId ?? '',
      name: normalized.name,
      base_url: normalized.baseUrl,
      health_endpoint: normalized.healthEndpoint,
      root_path: normalized.rootPath || undefined,
      agent_hub_permission: syncAgentHubPermission
        ? {
            permission_tier: permissionTier,
            auto_exec_enabled: autoExecEnabled,
            execution_start_hour: 0,
            execution_end_hour: 24,
          }
        : undefined,
    })
  }

  const normalizedRootPath = normalizeRootPath(rootPath)
  const healthPreview = buildHealthPreview(baseUrl, healthEndpoint)

  return (
    <div className="mx-auto max-w-4xl space-y-4 px-4 py-4 md:px-5 lg:px-6">
      <header className="animate-in">
        <Link
          href="/"
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
              Root URL used for health checks and operator links.
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
              Strongly recommended. Enables file browsing, service config discovery, and safer project-aware automation.
            </p>
            {errors.rootPath && (
              <p className="text-xs text-rose-400">{errors.rootPath}</p>
            )}
          </div>

          <div className="chrome-line my-1" />

          <div className="space-y-3 rounded-xl border border-slate-800/70 bg-slate-950/40 p-4">
            <div className="space-y-1">
              <div className="text-sm font-medium text-slate-100">
                Agent Hub Access Bootstrap
              </div>
              <p className="text-xs text-slate-500">
                Create the matching project permission row at the same time so the new project is immediately visible to Jenny and specialist agents.
              </p>
            </div>

            <label className="flex items-center gap-2 text-sm text-slate-300">
              <input
                type="checkbox"
                checked={syncAgentHubPermission}
                onChange={(event) => setSyncAgentHubPermission(event.target.checked)}
                className="h-4 w-4 rounded border-slate-700 bg-slate-950"
              />
              Provision Agent Hub permission
            </label>

            {syncAgentHubPermission && (
              <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_180px]">
                <div className="space-y-2">
                  <Label htmlFor="permissionTier">Permission Tier</Label>
                  <select
                    id="permissionTier"
                    value={permissionTier}
                    onChange={(event) => setPermissionTier(event.target.value)}
                    className="flex h-10 w-full rounded-md border border-slate-800 bg-slate-950 px-3 text-sm text-slate-100"
                  >
                    <option value="off">Off</option>
                    <option value="read">Read</option>
                    <option value="write">Write</option>
                    <option value="yolo">YOLO</option>
                  </select>
                </div>

                <label className="flex items-center gap-2 rounded-md border border-slate-800 bg-slate-950 px-3 text-sm text-slate-300">
                  <input
                    type="checkbox"
                    checked={autoExecEnabled}
                    onChange={(event) => setAutoExecEnabled(event.target.checked)}
                    className="h-4 w-4 rounded border-slate-700 bg-slate-950"
                  />
                  Auto Exec
                </label>
              </div>
            )}
          </div>

          <div className="flex items-center gap-3 pt-2">
            <button
              type="submit"
              disabled={mutation.isPending}
              className="btn-primary flex items-center gap-2 text-sm"
            >
              {mutation.isPending ? (
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
            <Link href="/" className="btn-secondary text-sm">
              Cancel
            </Link>
          </div>
        </form>

        <aside className="space-y-3">
          <div className="card space-y-3 p-4">
            <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
              Live preview
            </div>

            <div className="space-y-2 text-xs text-slate-400">
              <div>
                <span className="text-[10px] uppercase tracking-[0.14em] text-slate-500">Project ID</span>
                <div className="mt-1 break-all rounded-md border border-slate-800/70 bg-slate-950/60 px-2 py-1.5 font-mono text-slate-200">
                  {projectId || <span className="text-slate-600">not-set</span>}
                </div>
              </div>
              <div>
                <span className="text-[10px] uppercase tracking-[0.14em] text-slate-500">Health Check</span>
                <div className="mt-1 break-all rounded-md border border-slate-800/70 bg-slate-950/60 px-2 py-1.5 font-mono text-slate-200">
                  {healthPreview}
                </div>
              </div>
              <div>
                <span className="text-[10px] uppercase tracking-[0.14em] text-slate-500">Root Path</span>
                <div className="mt-1 break-all rounded-md border border-slate-800/70 bg-slate-950/60 px-2 py-1.5 font-mono text-slate-200">
                  {normalizedRootPath || <span className="text-slate-600">not configured</span>}
                </div>
              </div>
              <div>
                <span className="text-[10px] uppercase tracking-[0.14em] text-slate-500">Agent Hub Access</span>
                <div className="mt-1 rounded-md border border-slate-800/70 bg-slate-950/60 px-2 py-1.5 font-mono text-slate-200">
                  {syncAgentHubPermission ? `${permissionTier}${autoExecEnabled ? ' + auto-exec' : ''}` : 'disabled'}
                </div>
              </div>
            </div>
          </div>

          <div className="card space-y-2 p-4">
            <div className="flex items-center gap-2 text-sm font-medium text-slate-200">
              <HeartPulse className="h-4 w-4 text-emerald-400" />
              Operational Coverage
            </div>
            <div className="space-y-3 text-xs text-slate-400">
              <p>
                Health checks start working as soon as the base URL and endpoint are correct.
              </p>
              <div className="flex items-start gap-2 rounded-lg border border-slate-800 bg-slate-950/50 p-3">
                <FolderTree className="mt-0.5 h-4 w-4 text-phosphor-400" />
                <div>
                  <p className="text-slate-300">Root path unlocks the rest</p>
                  <p className="mt-1">
                    Without a repo path, SummitFlow can still track metadata, but file browsing and service discovery stay blind.
                  </p>
                </div>
              </div>
            </div>
          </div>
        </aside>
      </div>
    </div>
  )
}
