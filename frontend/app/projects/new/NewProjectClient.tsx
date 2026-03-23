'use client'

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
    })
  }

  const normalizedRootPath = normalizeRootPath(rootPath)
  const healthPreview = buildHealthPreview(baseUrl, healthEndpoint)

  return (
    <div className="mx-auto max-w-3xl space-y-6 p-6">
      <header className="animate-in">
        <Link
          href="/"
          className="mb-3 flex items-center gap-1 text-xs text-slate-500 transition-colors hover:text-phosphor-400"
        >
          <ArrowLeft className="h-3 w-3" />
          Back to Dashboard
        </Link>

        <div className="flex items-center gap-4">
          <div className="flex h-14 w-14 items-center justify-center rounded-xl bg-slate-800">
            <FolderPlus className="h-7 w-7 text-phosphor-400" />
          </div>
          <div>
            <h1 className="display text-2xl font-bold text-slate-100 tracking-tight">
              Create Project
            </h1>
            <p className="mt-1 text-sm text-slate-400">
              Register the app once, then let SummitFlow track health, scans, and active work against a real root path.
            </p>
          </div>
        </div>
      </header>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_280px]">
        <form onSubmit={handleSubmit} className="card space-y-5 p-6">
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
              className={`mono ${errors.projectId ? 'border-rose-500/50' : ''}`}
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

          <div className="space-y-2">
            <Label htmlFor="healthEndpoint">Health Endpoint</Label>
            <Input
              id="healthEndpoint"
              value={healthEndpoint}
              onChange={(e) => handleHealthEndpointChange(e.target.value)}
              placeholder={DEFAULT_HEALTH_ENDPOINT}
              aria-invalid={Boolean(errors.healthEndpoint)}
              className={`mono ${errors.healthEndpoint ? 'border-rose-500/50' : ''}`}
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
              className={`mono ${errors.rootPath ? 'border-rose-500/50' : ''}`}
            />
            <p className="text-xs text-slate-500">
              Strongly recommended. Enables file browsing, service config discovery, and safer project-aware automation.
            </p>
            {errors.rootPath && (
              <p className="text-xs text-rose-400">{errors.rootPath}</p>
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

        <aside className="space-y-4">
          <div className="card space-y-4 p-5">
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-slate-500">
                Registration Preview
              </p>
              <p className="mt-1 text-sm text-slate-400">
                SummitFlow will use these normalized values immediately after create.
              </p>
            </div>

            <div className="space-y-3 text-xs text-slate-400">
              <div>
                <span className="text-slate-500">Project ID</span>
                <div className="mt-1 break-all font-mono text-slate-200">
                  {projectId || 'not-set'}
                </div>
              </div>
              <div>
                <span className="text-slate-500">Health Check</span>
                <div className="mt-1 break-all font-mono text-slate-200">
                  {healthPreview}
                </div>
              </div>
              <div>
                <span className="text-slate-500">Root Path</span>
                <div className="mt-1 break-all font-mono text-slate-200">
                  {normalizedRootPath || 'not configured'}
                </div>
              </div>
            </div>
          </div>

          <div className="card space-y-3 p-5">
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
