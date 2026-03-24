'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import {
  AlertCircle,
  ArrowLeft,
  Bot,
  ExternalLink,
  FolderTree,
  Gauge,
  HeartPulse,
  Loader2,
  RefreshCcw,
  Save,
  Settings2,
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
type SettingsTab = 'general' | 'automation'

export function ProjectSettingsClient() {
  const params = useParams()
  const projectId = params.id as string
  const queryClient = useQueryClient()

  const [activeTab, setActiveTab] = useState<SettingsTab>('general')
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
      if (!(field in current) && !('submit' in current)) return current
      const next = { ...current }
      delete next[field]
      delete next.submit
      return next
    })
    setSaveState(null)
  }

  const currentValues = normalizeProjectFormValues({ name, baseUrl, healthEndpoint, rootPath })
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
    { name, baseUrl, healthEndpoint, rootPath },
    { requireProjectId: false },
  )
  const canSave = hasChanges && Object.keys(fieldErrors).length === 0 && !mutation.isPending
  const healthPreview = buildHealthPreview(baseUrl, healthEndpoint)

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault()
    const validationErrors = validateProjectForm(
      { name, baseUrl, healthEndpoint, rootPath },
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
              <h1 className="text-lg font-semibold text-slate-100 display">
                Unable to load project settings
              </h1>
              <p className="mt-1 text-sm text-slate-400">
                {getErrorMessage(error, 'The project settings request failed.')}
              </p>
              <div className="mt-4 flex items-center gap-3">
                <Link href={`/projects/${projectId}`} className="text-sm text-phosphor-400 hover:text-phosphor-300">
                  Back to project
                </Link>
                <Link href="/" className="text-sm text-slate-400 hover:text-slate-200">
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
          <h1 className="text-lg font-semibold text-slate-100 display">Project not found</h1>
          <p className="mt-1 text-sm text-slate-400">
            This project no longer exists or has not been registered yet.
          </p>
          <Link href="/" className="mt-4 inline-flex text-sm text-phosphor-400 hover:text-phosphor-300">
            Back to dashboard
          </Link>
        </div>
      </main>
    )
  }

  const serviceEntries = Object.values(services?.services ?? {}).sort(
    (left, right) => left.port - right.port,
  )

  const tabs: { id: SettingsTab; label: string; icon: typeof Settings2 }[] = [
    { id: 'general', label: 'General', icon: Settings2 },
    { id: 'automation', label: 'Automation', icon: Bot },
  ]

  return (
    <main className="content-container py-8 max-w-4xl">
      {/* Header */}
      <header className="mb-6 flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <Link
            href={`/projects/${projectId}`}
            className="text-slate-400 transition-colors hover:text-slate-200"
          >
            <ArrowLeft className="h-5 w-5" />
          </Link>
          <div>
            <h1 className="display flex items-center gap-2.5 text-xl font-bold text-slate-100">
              Settings
            </h1>
            <p className="mt-0.5 text-sm text-slate-500">{project.name}</p>
          </div>
        </div>
      </header>

      {/* Status Strip */}
      <div className="mb-6 grid grid-cols-2 lg:grid-cols-4 gap-3">
        <StatusCell
          label="Project ID"
          value={project.id}
          helper={`Created ${new Date(project.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}`}
          icon={Gauge}
          mono
        />
        <StatusCell
          label="Health"
          value={
            health
              ? health.healthy
                ? health.response_time_ms != null
                  ? `${Math.round(health.response_time_ms)}ms`
                  : 'Healthy'
                : health.error || `HTTP ${health.status_code ?? 'err'}`
              : 'Not checked'
          }
          helper={healthPreview}
          icon={HeartPulse}
          tone={health?.healthy === false ? 'rose' : health ? 'emerald' : 'default'}
          actionLabel="Refresh"
          onAction={() => refetchHealth()}
          pending={healthRefreshing}
        />
        <StatusCell
          label="Quality Gate"
          value={
            qualityGate
              ? qualityGate.overall_pass
                ? 'Passing'
                : `${qualityGate.total_unfixed} open`
              : 'Unavailable'
          }
          helper={qualityGate ? (qualityGate.overall_pass ? 'No unfixed issues' : 'Needs attention') : 'Not loaded'}
          icon={AlertCircle}
          tone={qualityGate ? (qualityGate.overall_pass ? 'emerald' : 'amber') : 'default'}
        />
        <StatusCell
          label="Services"
          value={project.root_path ? `${serviceEntries.length} configured` : 'No root path'}
          helper={
            project.root_path
              ? services?.config_source === 'file'
                ? '.st/services.yaml'
                : 'Default map'
              : 'Add root path to unlock'
          }
          icon={FolderTree}
          tone={project.root_path ? 'cyan' : 'amber'}
          actionLabel={project.root_path ? 'Reload' : undefined}
          onAction={project.root_path ? () => refetchServices() : undefined}
          pending={servicesRefreshing}
        />
      </div>

      {/* Tab Bar */}
      <div className="flex items-center gap-1 mb-6 border-b border-slate-800/60">
        {tabs.map((tab) => {
          const Icon = tab.icon
          return (
            <button
              key={tab.id}
              type="button"
              onClick={() => setActiveTab(tab.id)}
              className={clsx(
                'flex items-center gap-2 px-4 py-2.5 text-sm font-medium transition-all border-b-2 -mb-px focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-outrun-500/40',
                activeTab === tab.id
                  ? 'border-outrun-500 text-slate-100 bg-outrun-500/5 shadow-[0_2px_8px_rgba(255,0,102,0.15)]'
                  : 'border-transparent text-slate-500 hover:text-slate-300 hover:border-slate-700',
              )}
            >
              <Icon className={clsx('w-4 h-4', activeTab === tab.id && 'text-outrun-400')} />
              {tab.label}
            </button>
          )
        })}
      </div>

      {/* Tab Content */}
      {activeTab === 'general' && (
        <div className="space-y-6 animate-in">
          {/* Registration Form */}
          <form onSubmit={handleSave} className="card space-y-5 rounded-xl p-6">
            <div>
              <h2 className="text-base font-semibold text-slate-100">Registration Details</h2>
              <p className="mt-1 text-sm text-slate-400">
                Health checks, file surfaces, and operator links use these values.
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
                  onChange={(e) => { clearError('name'); setName(e.target.value) }}
                  aria-invalid={Boolean(errors.name)}
                  className={errors.name ? 'border-red-500/50' : ''}
                />
                {errors.name && <p className="text-xs text-red-400">{errors.name}</p>}
              </div>

              <div className="space-y-2">
                <Label htmlFor="project-id">Project ID</Label>
                <Input id="project-id" value={project.id} disabled className="mono text-slate-400" />
                <p className="text-xs text-slate-500">Stable identifier, not editable inline.</p>
              </div>

              <div className="space-y-2">
                <Label htmlFor="project-base-url">Base URL *</Label>
                <Input
                  id="project-base-url"
                  value={baseUrl}
                  onChange={(e) => { clearError('baseUrl'); setBaseUrl(e.target.value) }}
                  aria-invalid={Boolean(errors.baseUrl)}
                  className={errors.baseUrl ? 'border-red-500/50' : ''}
                />
                {errors.baseUrl && <p className="text-xs text-red-400">{errors.baseUrl}</p>}
              </div>

              <div className="space-y-2">
                <Label htmlFor="project-health-endpoint">Health Endpoint</Label>
                <Input
                  id="project-health-endpoint"
                  value={healthEndpoint}
                  onChange={(e) => { clearError('healthEndpoint'); setHealthEndpoint(e.target.value) }}
                  aria-invalid={Boolean(errors.healthEndpoint)}
                  className={`mono ${errors.healthEndpoint ? 'border-red-500/50' : ''}`}
                />
                {errors.healthEndpoint && <p className="text-xs text-red-400">{errors.healthEndpoint}</p>}
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="project-root-path">Root Path</Label>
              <Input
                id="project-root-path"
                value={rootPath}
                onChange={(e) => { clearError('rootPath'); setRootPath(e.target.value) }}
                aria-invalid={Boolean(errors.rootPath)}
                className={`mono ${errors.rootPath ? 'border-red-500/50' : ''}`}
                placeholder="/home/user/projects/my-project"
              />
              <p className="text-xs text-slate-500">
                Required for file browsing, service discovery, and path-aware automation.
              </p>
              {errors.rootPath && <p className="text-xs text-red-400">{errors.rootPath}</p>}
            </div>

            <div className="rounded-lg border border-slate-800 bg-slate-950/50 p-3 text-sm">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <p className="text-2xs font-medium uppercase tracking-wide text-slate-500">Effective health check</p>
                  <p className="mt-0.5 break-all font-mono text-sm text-slate-200">{healthPreview}</p>
                </div>
                <a
                  href={currentValues.baseUrl || project.base_url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 text-xs text-phosphor-400 hover:text-phosphor-300"
                >
                  <ExternalLink className="h-3 w-3" /> Open
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
                  <><Loader2 className="h-4 w-4 animate-spin" /> Saving...</>
                ) : (
                  <><Save className="h-4 w-4" /> Save Changes</>
                )}
              </button>
              <button
                type="button"
                onClick={handleReset}
                disabled={!hasChanges || mutation.isPending}
                className="btn-secondary inline-flex items-center gap-2 text-sm disabled:cursor-not-allowed disabled:opacity-50"
              >
                <RefreshCcw className="h-4 w-4" /> Reset
              </button>
              <span className="text-xs text-slate-500">
                {hasChanges ? 'Unsaved changes' : 'In sync'}
              </span>
            </div>
          </form>

          {/* Services */}
          <div className="card rounded-xl p-6">
            <div className="mb-4">
              <h2 className="text-base font-semibold text-slate-100">Service Configuration</h2>
              <p className="mt-1 text-sm text-slate-400">
                Services SummitFlow uses for reasoning about this project&apos;s runtime.
              </p>
            </div>

            {!project.root_path ? (
              <div className="rounded-lg border border-amber-500/20 bg-amber-500/10 p-4 text-sm text-amber-200">
                Add a root path above to enable service discovery.
              </div>
            ) : servicesError ? (
              <div className="rounded-lg border border-rose-500/20 bg-rose-500/10 p-4 text-sm text-rose-200">
                {getErrorMessage(servicesError, 'Unable to load service configuration.')}
              </div>
            ) : serviceEntries.length === 0 ? (
              <div className="rounded-lg border border-slate-800 bg-slate-950/50 p-4 text-sm text-slate-400">
                No services detected yet.
              </div>
            ) : (
              <div className="space-y-2">
                <div className="flex items-center justify-between text-xs text-slate-500">
                  <span>
                    Source:{' '}
                    <span className="text-slate-300">
                      {services?.config_source === 'file' ? '.st/services.yaml' : 'default config'}
                    </span>
                  </span>
                  <span>{serviceEntries.length} service{serviceEntries.length === 1 ? '' : 's'}</span>
                </div>
                {serviceEntries.map((service) => (
                  <div key={service.name} className="rounded-lg border border-slate-800 bg-slate-950/50 p-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div>
                        <p className="text-sm font-medium text-slate-100">{service.name}</p>
                        <p className="text-xs text-slate-500">
                          Port {service.port} · worktree base {service.worktree_port_base}
                        </p>
                      </div>
                      {service.cwd && (
                        <span className="rounded-full border border-slate-700 px-2 py-0.5 font-mono text-2xs text-slate-400">
                          {service.cwd}
                        </span>
                      )}
                    </div>
                    <p className="mt-2 break-all font-mono text-xs text-slate-300">{service.command}</p>
                    {(service.build_command || service.env_file) && (
                      <div className="mt-2 flex flex-wrap gap-2 text-2xs text-slate-500">
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
      )}

      {activeTab === 'automation' && (
        <div className="animate-in">
          <div className="card rounded-xl p-6">
            <p className="mb-5 text-sm text-slate-400">
              Autonomous execution, quality gates, and merge posture for{' '}
              <span className="text-slate-200">{project.name}</span>.
            </p>
            <AutonomousSettingsPanel projectId={projectId} />
          </div>
        </div>
      )}
    </main>
  )
}

interface StatusCellProps {
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

function StatusCell({
  label,
  value,
  helper,
  icon: Icon,
  tone = 'default',
  actionLabel,
  onAction,
  pending = false,
  mono = false,
}: StatusCellProps) {
  const toneClasses: Record<string, { text: string; icon: string; iconBg: string }> = {
    default: { text: 'text-slate-100', icon: 'text-slate-400', iconBg: 'bg-slate-500/10' },
    emerald: { text: 'text-emerald-300', icon: 'text-emerald-400', iconBg: 'bg-emerald-500/10' },
    rose: { text: 'text-rose-300', icon: 'text-rose-400', iconBg: 'bg-rose-500/10' },
    amber: { text: 'text-amber-300', icon: 'text-amber-400', iconBg: 'bg-amber-500/10' },
    cyan: { text: 'text-cyan-300', icon: 'text-cyan-400', iconBg: 'bg-cyan-500/10' },
  }

  const tc = toneClasses[tone]

  return (
    <div className="card px-4 py-3.5 transition-all duration-200 hover:border-slate-600/60">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-2xs uppercase tracking-wider text-slate-500">
          <div className={`rounded-md p-1.5 ${tc.iconBg}`}>
            <Icon className={`h-3 w-3 ${tc.icon}`} />
          </div>
          <span className="font-medium">{label}</span>
        </div>
        {actionLabel && onAction ? (
          <button
            type="button"
            onClick={onAction}
            className="text-[10px] text-slate-600 transition-colors hover:text-slate-300"
          >
            {pending ? 'Loading...' : actionLabel}
          </button>
        ) : null}
      </div>
      <div className={clsx('mt-2 text-sm truncate font-semibold', mono && 'font-mono', tc.text)}>
        {value}
      </div>
      <div className="mt-0.5 truncate text-2xs text-slate-600">{helper}</div>
    </div>
  )
}
