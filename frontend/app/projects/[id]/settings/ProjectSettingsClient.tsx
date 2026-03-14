'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertCircle,
  ArrowLeft,
  ExternalLink,
  FolderGit2,
  FolderTree,
  Gauge,
  HeartPulse,
  Loader2,
  RefreshCcw,
  Save,
  Settings2,
  Sparkles,
} from 'lucide-react'
import Link from 'next/link'
import { useParams } from 'next/navigation'
import { useEffect, useState } from 'react'
import { AutonomousSettingsPanel } from '@/components/settings/AutonomousSettings'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  fetchProject,
  fetchProjectHealth,
  fetchProjectServices,
  fetchQualityGateHealth,
  updateProject,
} from '@/lib/api'
import {
  buildHealthPreview,
  normalizeProjectFormValues,
  type ProjectFormErrors,
  validateProjectForm,
} from '@/lib/project-registration'
import { getErrorMessage } from '@/lib/utils'

type FormErrors = ProjectFormErrors & { submit?: string }
type ErrorField = keyof FormErrors

export function ProjectSettingsClient() {
  const params = useParams()
  const projectId = params.id as string
  const queryClient = useQueryClient()

  const [name, setName] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [healthEndpoint, setHealthEndpoint] = useState('')
  const [rootPath, setRootPath] = useState('')
  const [errors, setErrors] = useState<FormErrors>({})
  const [saveState, setSaveState] = useState<string | null>(null)

  const {
    data: project,
    isLoading: projectLoading,
    error,
  } = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => fetchProject(projectId),
  })

  const { data: health, refetch: refetchHealth, isFetching: healthRefreshing } = useQuery({
    queryKey: ['project-health', projectId],
    queryFn: () => fetchProjectHealth(projectId),
    enabled: Boolean(project),
  })

  const { data: qualityGate } = useQuery({
    queryKey: ['quality-gate-health', projectId],
    queryFn: () => fetchQualityGateHealth(projectId),
    enabled: Boolean(project),
  })

  const {
    data: services,
    error: servicesError,
    refetch: refetchServices,
    isFetching: servicesRefreshing,
  } = useQuery({
    queryKey: ['project-services', projectId],
    queryFn: () => fetchProjectServices(projectId),
    enabled: Boolean(project?.root_path),
  })

  useEffect(() => {
    if (!project) return
    setName(project.name)
    setBaseUrl(project.base_url)
    setHealthEndpoint(project.health_endpoint)
    setRootPath(project.root_path ?? '')
    setErrors({})
  }, [project])

  const mutation = useMutation({
    mutationFn: (payload: {
      name: string
      base_url: string
      health_endpoint: string
      root_path?: string
    }) => updateProject(projectId, payload),
    onSuccess: async (updatedProject) => {
      queryClient.setQueryData(['project', projectId], updatedProject)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['projects'] }),
        queryClient.invalidateQueries({ queryKey: ['projects-with-stats'] }),
        queryClient.invalidateQueries({ queryKey: ['project-health', projectId] }),
        queryClient.invalidateQueries({ queryKey: ['project-services', projectId] }),
      ])
      setSaveState('Project registration details saved.')
    },
    onError: (mutationError: Error) => {
      setErrors((current) => ({
        ...current,
        submit: mutationError.message,
      }))
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
    setSaveState(null)
  }

  const currentValues = normalizeProjectFormValues({
    name,
    baseUrl,
    healthEndpoint,
    rootPath,
  })
  const persistedValues = normalizeProjectFormValues({
    name: project?.name ?? '',
    baseUrl: project?.base_url ?? '',
    healthEndpoint: project?.health_endpoint ?? '',
    rootPath: project?.root_path ?? '',
  })
  const hasChanges =
    !!project &&
    (currentValues.name !== persistedValues.name ||
      currentValues.baseUrl !== persistedValues.baseUrl ||
      currentValues.healthEndpoint !== persistedValues.healthEndpoint ||
      currentValues.rootPath !== persistedValues.rootPath)
  const fieldErrors = validateProjectForm(
    {
      name,
      baseUrl,
      healthEndpoint,
      rootPath,
    },
    { requireProjectId: false },
  )
  const canSave = hasChanges && Object.keys(fieldErrors).length === 0 && !mutation.isPending
  const healthPreview = buildHealthPreview(baseUrl, healthEndpoint)

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault()
    const validationErrors = validateProjectForm(
      {
        name,
        baseUrl,
        healthEndpoint,
        rootPath,
      },
      { requireProjectId: false },
    )
    setErrors(validationErrors)
    if (Object.keys(validationErrors).length > 0) return

    mutation.mutate({
      name: currentValues.name,
      base_url: currentValues.baseUrl,
      health_endpoint: currentValues.healthEndpoint,
      root_path: currentValues.rootPath || undefined,
    })
  }

  const handleReset = () => {
    if (!project) return
    setName(project.name)
    setBaseUrl(project.base_url)
    setHealthEndpoint(project.health_endpoint)
    setRootPath(project.root_path ?? '')
    setErrors({})
    setSaveState(null)
  }

  if (projectLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-slate-400" />
      </div>
    )
  }

  if (error) {
    return (
      <main className="content-container py-8">
        <div className="card max-w-xl p-6">
          <div className="flex items-start gap-3">
            <AlertCircle className="mt-0.5 h-5 w-5 text-rose-400" />
            <div>
              <h1 className="text-lg font-semibold text-slate-100">
                Unable to load project settings
              </h1>
              <p className="mt-1 text-sm text-slate-400">
                {getErrorMessage(error, 'The project settings request failed.')}
              </p>
              <div className="mt-4 flex items-center gap-3">
                <Link
                  href={`/projects/${projectId}`}
                  className="text-sm text-phosphor-400 hover:text-phosphor-300"
                >
                  Back to project
                </Link>
                <Link
                  href="/"
                  className="text-sm text-slate-400 hover:text-slate-200"
                >
                  Dashboard
                </Link>
              </div>
            </div>
          </div>
        </div>
      </main>
    )
  }

  if (!project) {
    return (
      <main className="content-container py-8">
        <div className="card max-w-xl p-6">
          <h1 className="text-lg font-semibold text-slate-100">
            Project not found
          </h1>
          <p className="mt-1 text-sm text-slate-400">
            This project no longer exists or has not been registered yet.
          </p>
          <Link
            href="/"
            className="mt-4 inline-flex text-sm text-phosphor-400 hover:text-phosphor-300"
          >
            Back to dashboard
          </Link>
        </div>
      </main>
    )
  }

  const serviceEntries = Object.values(services?.services ?? {}).sort(
    (left, right) => left.port - right.port,
  )

  return (
    <main className="content-container py-8">
      <header className="mb-8 flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-4">
          <Link
            href={`/projects/${projectId}`}
            className="text-slate-400 transition-colors hover:text-slate-200"
          >
            <ArrowLeft className="h-5 w-5" />
          </Link>
          <div>
            <h1 className="flex items-center gap-3 text-2xl font-semibold text-slate-100">
              <Settings2 className="h-6 w-6 text-slate-400" />
              Project Settings
            </h1>
            <p className="mt-1 text-sm text-slate-400">
              {project.name} · registration, live health, and autonomous controls
            </p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Link
            href={`/projects/${projectId}`}
            className="btn-secondary inline-flex items-center gap-2 text-sm"
          >
            <Sparkles className="h-4 w-4" />
            Project Overview
          </Link>
          <Link
            href={`/projects/${projectId}/git`}
            className="btn-secondary inline-flex items-center gap-2 text-sm"
          >
            <FolderGit2 className="h-4 w-4" />
            Git
          </Link>
          <Link
            href={`/projects/${projectId}/files`}
            className="btn-secondary inline-flex items-center gap-2 text-sm"
          >
            <FolderTree className="h-4 w-4" />
            Files
          </Link>
        </div>
      </header>

      <section className="mb-6 grid gap-4 xl:grid-cols-4">
        <StatusCard
          label="Project ID"
          value={project.id}
          helper={`Created ${new Date(project.created_at).toLocaleDateString()}`}
          icon={Gauge}
          mono
        />
        <StatusCard
          label="Health Check"
          value={
            health
              ? health.healthy
                ? health.response_time_ms != null
                  ? `${Math.round(health.response_time_ms)}ms`
                  : 'Healthy'
                : health.error || `HTTP ${health.status_code ?? 'error'}`
              : 'Not checked yet'
          }
          helper={healthPreview}
          icon={HeartPulse}
          tone={health?.healthy === false ? 'rose' : health ? 'emerald' : 'default'}
          actionLabel="Refresh"
          onAction={() => refetchHealth()}
          pending={healthRefreshing}
        />
        <StatusCard
          label="Quality Gate"
          value={
            qualityGate
              ? qualityGate.overall_pass
                ? 'Passing'
                : `${qualityGate.total_unfixed} open`
              : 'Unavailable'
          }
          helper={
            qualityGate
              ? qualityGate.overall_pass
                ? 'No unfixed quality issues'
                : 'Needs operator attention'
              : 'Quality status not loaded'
          }
          icon={AlertCircle}
          tone={
            qualityGate
              ? qualityGate.overall_pass
                ? 'emerald'
                : 'amber'
              : 'default'
          }
        />
        <StatusCard
          label="Services"
          value={project.root_path ? `${serviceEntries.length} configured` : 'Root path required'}
          helper={
            project.root_path
              ? services?.config_source === 'file'
                ? '.st/services.yaml detected'
                : 'Using default service map'
              : 'Add a root path to unlock service discovery'
          }
          icon={FolderTree}
          tone={project.root_path ? 'cyan' : 'amber'}
          actionLabel={project.root_path ? 'Reload' : undefined}
          onAction={project.root_path ? () => refetchServices() : undefined}
          pending={servicesRefreshing}
        />
      </section>

      <section className="grid gap-6 xl:grid-cols-[minmax(0,1.15fr)_minmax(0,0.85fr)]">
        <div className="space-y-6">
          <form onSubmit={handleSave} className="card space-y-5 rounded-xl p-6">
            <div>
              <h2 className="text-lg font-semibold text-slate-100">
                Registration Details
              </h2>
              <p className="mt-1 text-sm text-slate-400">
                Keep these accurate so health checks, file surfaces, and operator links point at the real system.
              </p>
            </div>

            {errors.submit && (
              <div className="flex items-center gap-2 rounded-lg border border-red-500/20 bg-red-500/10 p-3 text-sm text-red-400">
                <AlertCircle className="h-4 w-4 shrink-0" />
                {errors.submit}
              </div>
            )}
            {saveState && (
              <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/10 p-3 text-sm text-emerald-300">
                {saveState}
              </div>
            )}

            <div className="grid gap-5 md:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="project-name">Project Name *</Label>
                <Input
                  id="project-name"
                  value={name}
                  onChange={(e) => {
                    clearError('name')
                    setName(e.target.value)
                  }}
                  aria-invalid={Boolean(errors.name)}
                  className={errors.name ? 'border-red-500/50' : ''}
                />
                {errors.name && <p className="text-xs text-red-400">{errors.name}</p>}
              </div>

              <div className="space-y-2">
                <Label htmlFor="project-id">Project ID</Label>
                <Input
                  id="project-id"
                  value={project.id}
                  disabled
                  className="mono text-slate-400"
                />
                <p className="text-xs text-slate-500">
                  Stable identifier. Change it through migration, not an inline rename.
                </p>
              </div>

              <div className="space-y-2">
                <Label htmlFor="project-base-url">Base URL *</Label>
                <Input
                  id="project-base-url"
                  value={baseUrl}
                  onChange={(e) => {
                    clearError('baseUrl')
                    setBaseUrl(e.target.value)
                  }}
                  aria-invalid={Boolean(errors.baseUrl)}
                  className={errors.baseUrl ? 'border-red-500/50' : ''}
                />
                {errors.baseUrl && (
                  <p className="text-xs text-red-400">{errors.baseUrl}</p>
                )}
              </div>

              <div className="space-y-2">
                <Label htmlFor="project-health-endpoint">Health Endpoint</Label>
                <Input
                  id="project-health-endpoint"
                  value={healthEndpoint}
                  onChange={(e) => {
                    clearError('healthEndpoint')
                    setHealthEndpoint(e.target.value)
                  }}
                  aria-invalid={Boolean(errors.healthEndpoint)}
                  className={`mono ${errors.healthEndpoint ? 'border-red-500/50' : ''}`}
                />
                {errors.healthEndpoint && (
                  <p className="text-xs text-red-400">{errors.healthEndpoint}</p>
                )}
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="project-root-path">Root Path</Label>
              <Input
                id="project-root-path"
                value={rootPath}
                onChange={(e) => {
                  clearError('rootPath')
                  setRootPath(e.target.value)
                }}
                aria-invalid={Boolean(errors.rootPath)}
                className={`mono ${errors.rootPath ? 'border-red-500/50' : ''}`}
                placeholder="/home/user/projects/my-project"
              />
              <p className="text-xs text-slate-500">
                Required for file browsing, project-specific service discovery, and path-aware automation.
              </p>
              {errors.rootPath && (
                <p className="text-xs text-red-400">{errors.rootPath}</p>
              )}
            </div>

            <div className="rounded-lg border border-slate-800 bg-slate-950/50 p-4 text-sm text-slate-400">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <p className="text-xs font-medium uppercase tracking-wide text-slate-500">
                    Effective health check
                  </p>
                  <p className="mt-1 break-all font-mono text-slate-200">
                    {healthPreview}
                  </p>
                </div>
                <a
                  href={currentValues.baseUrl || project.base_url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 text-xs text-phosphor-400 hover:text-phosphor-300"
                >
                  <ExternalLink className="h-3 w-3" />
                  Open base URL
                </a>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-3">
              <button
                type="submit"
                disabled={!canSave}
                className="btn-primary inline-flex items-center gap-2 text-sm disabled:cursor-not-allowed disabled:opacity-50"
              >
                {mutation.isPending ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Saving...
                  </>
                ) : (
                  <>
                    <Save className="h-4 w-4" />
                    Save Changes
                  </>
                )}
              </button>
              <button
                type="button"
                onClick={handleReset}
                disabled={!hasChanges || mutation.isPending}
                className="btn-secondary inline-flex items-center gap-2 text-sm disabled:cursor-not-allowed disabled:opacity-50"
              >
                <RefreshCcw className="h-4 w-4" />
                Reset
              </button>
              <span className="text-xs text-slate-500">
                {hasChanges ? 'Unsaved changes' : 'Registration details are in sync'}
              </span>
            </div>
          </form>

          <div className="card rounded-xl p-6">
            <div className="mb-4">
              <h2 className="text-lg font-semibold text-slate-100">
                Service Configuration
              </h2>
              <p className="mt-1 text-sm text-slate-400">
                This is what SummitFlow will use when it needs to reason about running services for this project.
              </p>
            </div>

            {!project.root_path ? (
              <div className="rounded-lg border border-amber-500/20 bg-amber-500/10 p-4 text-sm text-amber-200">
                Add a root path above to enable `.st/services.yaml` discovery and default service mapping.
              </div>
            ) : servicesError ? (
              <div className="rounded-lg border border-rose-500/20 bg-rose-500/10 p-4 text-sm text-rose-200">
                {getErrorMessage(servicesError, 'Unable to load service configuration.')}
              </div>
            ) : serviceEntries.length === 0 ? (
              <div className="rounded-lg border border-slate-800 bg-slate-950/50 p-4 text-sm text-slate-400">
                No services were detected for this project yet.
              </div>
            ) : (
              <div className="space-y-3">
                <div className="flex items-center justify-between text-xs text-slate-500">
                  <span>
                    Source:{' '}
                    <span className="text-slate-300">
                      {services?.config_source === 'file'
                        ? '.st/services.yaml'
                        : 'default config'}
                    </span>
                  </span>
                  <span>{serviceEntries.length} service{serviceEntries.length === 1 ? '' : 's'}</span>
                </div>
                {serviceEntries.map((service) => (
                  <div
                    key={service.name}
                    className="rounded-lg border border-slate-800 bg-slate-950/50 p-4"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div>
                        <p className="text-sm font-medium text-slate-100">
                          {service.name}
                        </p>
                        <p className="mt-1 text-xs text-slate-500">
                          Port {service.port} · worktree base {service.worktree_port_base}
                        </p>
                      </div>
                      {service.cwd && (
                        <span className="rounded-full border border-slate-700 px-2 py-1 font-mono text-[11px] text-slate-400">
                          {service.cwd}
                        </span>
                      )}
                    </div>
                    <p className="mt-3 break-all font-mono text-xs text-slate-300">
                      {service.command}
                    </p>
                    {(service.build_command || service.env_file) && (
                      <div className="mt-3 flex flex-wrap gap-2 text-[11px] text-slate-500">
                        {service.build_command && <span>Build: {service.build_command}</span>}
                        {service.env_file && <span>Env: {service.env_file}</span>}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="space-y-6">
          <section className="animate-fade-in">
            <div className="card rounded-xl p-6">
              <p className="mb-4 text-sm text-slate-400">
                Control autonomous execution, quality-gate behavior, and merge posture for{' '}
                <span className="text-slate-200">{project.name}</span>.
              </p>
              <AutonomousSettingsPanel projectId={projectId} />
            </div>
          </section>
        </div>
      </section>
    </main>
  )
}

interface StatusCardProps {
  label: string
  value: string
  helper: string
  icon: typeof Gauge
  tone?: 'default' | 'emerald' | 'rose' | 'amber' | 'cyan'
  actionLabel?: string
  onAction?: () => void
  pending?: boolean
  mono?: boolean
}

function StatusCard({
  label,
  value,
  helper,
  icon: Icon,
  tone = 'default',
  actionLabel,
  onAction,
  pending = false,
  mono = false,
}: StatusCardProps) {
  const valueTone =
    tone === 'emerald'
      ? 'text-emerald-300'
      : tone === 'rose'
        ? 'text-rose-300'
        : tone === 'amber'
          ? 'text-amber-300'
          : tone === 'cyan'
            ? 'text-cyan-300'
            : 'text-slate-100'

  return (
    <div className="card rounded-xl p-4">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-slate-500">
          <Icon className="h-3.5 w-3.5" />
          {label}
        </div>
        {actionLabel && onAction ? (
          <button
            type="button"
            onClick={onAction}
            className="text-[11px] text-slate-500 transition-colors hover:text-slate-300"
          >
            {pending ? 'Refreshing…' : actionLabel}
          </button>
        ) : null}
      </div>
      <div className={`mt-2 text-sm ${mono ? 'font-mono' : ''} ${valueTone}`}>
        {value}
      </div>
      <div className="mt-1 break-all text-xs text-slate-500">{helper}</div>
    </div>
  )
}
