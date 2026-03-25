'use client'

import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import {
  AlertCircle,
  Bug,
  Clock,
  Database,
  ExternalLink,
  ListTodo,
  Settings2,
  Target,
} from 'lucide-react'
import Image from 'next/image'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useState } from 'react'
import {
  fetchProjectHealth,
  fetchQualityGateHealth,
  type ProjectWithStats,
} from '@/lib/api'
import { getActiveCheckpoint } from '@/lib/api/checkpoints'
import { POLL_STANDARD, STALE_GIT, STALE_STANDARD } from '@/lib/polling'

interface ProjectCardProps {
  project: ProjectWithStats
}

function getProjectHost(baseUrl: string): string {
  try {
    return new URL(baseUrl).host
  } catch {
    return baseUrl
  }
}

// Gradient palette for project avatar fallbacks — keyed by first letter
const LETTER_GRADIENTS: Record<string, { from: string; to: string }> = {
  S: { from: '#00c853', to: '#009624' },
  P: { from: '#3b82f6', to: '#2563eb' },
  A: { from: '#8b5cf6', to: '#6d28d9' },
  C: { from: '#f59e0b', to: '#d97706' },
  B: { from: '#ec4899', to: '#be185d' },
  D: { from: '#06b6d4', to: '#0891b2' },
  default: { from: '#64748b', to: '#475569' },
}

export function ProjectCard({ project }: ProjectCardProps) {
  const router = useRouter()
  const [hovered, setHovered] = useState(false)

  const { data: health, isLoading: healthLoading } = useQuery({
    queryKey: ['project-health', project.id],
    queryFn: () => fetchProjectHealth(project.id),
    staleTime: STALE_STANDARD,
    refetchInterval: hovered ? POLL_STANDARD * 2 : false,
  })

  const { data: qualityGate, isLoading: qualityLoading } = useQuery({
    queryKey: ['quality-gate-health', project.id],
    queryFn: () => fetchQualityGateHealth(project.id),
    staleTime: STALE_STANDARD,
    refetchInterval: hovered ? POLL_STANDARD * 2 : false,
  })

  // Check for active checkpoint (running task)
  const { data: checkpoint } = useQuery({
    queryKey: ['active-checkpoint', project.id],
    queryFn: () => getActiveCheckpoint(project.id),
    staleTime: STALE_GIT,
  })

  const firstLetter = project.name.charAt(0).toUpperCase()
  const gradient = LETTER_GRADIENTS[firstLetter] ?? LETTER_GRADIENTS.default

  const { stats } = project
  const projectHost = getProjectHost(project.base_url)
  const metrics = [
    {
      key: 'features' as const,
      label: 'Features',
      title: 'View active features',
      count: stats.features,
      icon: Target,
      activeClass: 'text-blue-400 hover:text-blue-300',
    },
    {
      key: 'tasks' as const,
      label: 'Tasks',
      title: 'View active tasks',
      count: stats.tasks,
      icon: ListTodo,
      activeClass: 'text-purple-400 hover:text-purple-300',
    },
    {
      key: 'bugs' as const,
      label: 'Bugs',
      title: 'View active bugs',
      count: stats.bugs,
      icon: Bug,
      activeClass: 'text-amber-400 hover:text-amber-300',
    },
    {
      key: 'blocked' as const,
      label: 'Blocked',
      title: 'View blocked tasks',
      count: stats.blocked,
      icon: AlertCircle,
      activeClass: 'text-rose-400 hover:text-rose-300',
    },
  ]

  // Handle stat click - navigate to project with appropriate tab/filter
  const handleStatClick = (
    e: React.MouseEvent,
    type: 'features' | 'tasks' | 'bugs' | 'blocked',
  ) => {
    e.preventDefault()
    e.stopPropagation()

    switch (type) {
      case 'features':
        router.push(`/projects/${project.id}?tab=tasks&status=active&taskType=feature`)
        break
      case 'tasks':
        router.push(`/projects/${project.id}?tab=tasks&status=active&taskType=task`)
        break
      case 'bugs':
        router.push(
          `/projects/${project.id}?tab=tasks&status=active&taskType=bug`,
        )
        break
      case 'blocked':
        // Show blocked tasks (have incomplete dependencies)
        router.push(`/projects/${project.id}?tab=tasks&status=blocked`)
        break
    }
  }

  return (
    <article
      className="card-interactive group flex h-full flex-col p-6"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onFocusCapture={() => setHovered(true)}
    >
      <div className="pointer-events-none absolute inset-x-6 top-0 h-px bg-[linear-gradient(90deg,transparent,rgba(255,255,255,0.18),transparent)] opacity-70" />
      <div className="flex items-start justify-between gap-4">
        <div className="flex min-w-0 items-start gap-4">
          {project.logo_url ? (
            <div className="flex h-14 w-14 items-center justify-center overflow-hidden rounded-2xl border border-slate-700/60 bg-slate-800/80 shadow-[0_18px_36px_-30px_rgba(0,0,0,0.95)]">
              <Image
                src={project.logo_url}
                alt={project.name}
                width={56}
                height={56}
                className="object-cover w-full h-full"
              />
            </div>
          ) : (
            <div
              className="flex h-14 w-14 items-center justify-center rounded-2xl border border-white/10 shadow-[0_18px_36px_-30px_rgba(0,0,0,0.95)]"
              style={{
                background: `linear-gradient(135deg, ${gradient.from} 0%, ${gradient.to} 100%)`,
              }}
            >
              <span className="display text-xl font-bold text-slate-100">
                {firstLetter}
              </span>
            </div>
          )}
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <Link
                href={`/projects/${project.id}`}
                className="display text-lg font-semibold text-slate-100 transition-colors hover:text-phosphor-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-phosphor-500/60 rounded-sm"
              >
                {project.name}
              </Link>
              <span className="rounded-full border border-slate-700/60 bg-slate-900/70 px-2 py-0.5 text-[10px] uppercase tracking-[0.16em] text-slate-400">
                {project.id}
              </span>
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-500">
              <span className="rounded-full border border-slate-700/60 bg-slate-900/70 px-2.5 py-1 font-mono text-slate-300">
                {projectHost}
              </span>
              {project.root_path ? (
                <span
                  className="max-w-[260px] truncate rounded-full border border-slate-800/70 bg-slate-900/60 px-2.5 py-1 font-mono text-slate-500"
                  title={project.root_path}
                >
                  {project.root_path}
                </span>
              ) : (
                <span className="rounded-full border border-amber-500/20 bg-amber-500/10 px-2.5 py-1 text-amber-300">
                  Root path missing
                </span>
              )}
            </div>
            <div className="mt-4 flex flex-wrap items-center gap-2 text-[11px]">
              <span
                className={clsx(
                  'rounded-full border px-2.5 py-1 uppercase tracking-[0.16em]',
                  health?.healthy === false
                    ? 'border-rose-500/20 bg-rose-500/10 text-rose-300'
                    : 'border-emerald-500/20 bg-emerald-500/10 text-emerald-300',
                )}
              >
                {health
                  ? health.healthy
                    ? health.response_time_ms != null
                      ? `${Math.round(health.response_time_ms)}ms`
                      : 'healthy'
                    : 'service issue'
                  : 'service pending'}
              </span>
              <span
                className={clsx(
                  'rounded-full border px-2.5 py-1 uppercase tracking-[0.16em]',
                  qualityGate && !qualityGate.overall_pass
                    ? 'border-amber-500/20 bg-amber-500/10 text-amber-300'
                    : 'border-violet-500/20 bg-violet-500/10 text-violet-300',
                )}
              >
                {qualityGate
                  ? qualityGate.overall_pass
                    ? 'quality passing'
                    : `${qualityGate.total_unfixed} open`
                  : 'quality pending'}
              </span>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2 rounded-full border border-slate-800/70 bg-slate-950/60 px-2.5 py-2 shadow-[inset_0_1px_0_rgba(255,255,255,0.03)]">
          {qualityLoading ? (
            <div className="w-3 h-3 border border-slate-600 border-t-purple-500 rounded-full animate-spin" />
          ) : qualityGate ? (
            <div
              className={clsx(
                'w-3 h-3 rounded-full status-dot-pulse',
                qualityGate.overall_pass
                  ? 'bg-purple-500 text-purple-500'
                  : 'bg-amber-500 text-amber-500',
              )}
              title={
                qualityGate.overall_pass
                  ? 'Quality gate passing'
                  : `Quality gate: ${qualityGate.total_unfixed} unfixed issues`
              }
              aria-label={
                qualityGate.overall_pass
                  ? 'Quality gate passing'
                  : `Quality gate has ${qualityGate.total_unfixed} unfixed issues`
              }
              data-testid="quality-gate-indicator"
            />
          ) : (
            <div
              className="w-3 h-3 rounded-full bg-slate-700"
              aria-label="Quality gate status unavailable"
              data-testid="quality-gate-indicator"
            />
          )}

          {healthLoading ? (
            <div className="w-3 h-3 border border-slate-600 border-t-phosphor-500 rounded-full animate-spin" />
          ) : health ? (
            <div
              className={clsx(
                'w-3 h-3 rounded-full status-dot-pulse',
                health.healthy
                  ? 'bg-green-500 text-green-500'
                  : 'bg-rose-500 text-rose-500',
              )}
              title={
                health.healthy
                  ? `Service healthy${health.response_time_ms ? ` (${Math.round(health.response_time_ms)}ms)` : ''}`
                  : `Service error: ${health.error || 'Unhealthy'}`
              }
              aria-label={
                health.healthy
                  ? 'Project service healthy'
                  : `Project service unhealthy${health.error ? `: ${health.error}` : ''}`
              }
              data-testid="project-health-indicator"
            />
          ) : (
            <div
              className="w-3 h-3 rounded-full bg-slate-600"
              aria-label="Project health status unavailable"
              data-testid="project-health-indicator"
            />
          )}
        </div>
      </div>

      {checkpoint && (
        <div className="mt-5 rounded-2xl border border-phosphor-500/14 bg-phosphor-500/8 px-4 py-3 text-xs text-phosphor-300">
          <div className="flex flex-wrap items-center gap-2">
            <Database className="h-3.5 w-3.5" />
            <span className="font-medium text-slate-100">Active checkpoint</span>
            <span className="font-mono">{checkpoint.task_id}</span>
            <span className="text-slate-500">{checkpoint.age}</span>
          </div>
        </div>
      )}

      <div className="mt-5 grid grid-cols-2 gap-2 xl:grid-cols-4">
        {metrics.map((metric) => {
          const Icon = metric.icon

          return (
            <button
              type="button"
              key={metric.key}
              onClick={(e) => handleStatClick(e, metric.key)}
              title={metric.title}
              className="rounded-2xl border border-slate-800/70 bg-slate-950/55 px-3 py-3 text-left transition-all duration-200 hover:-translate-y-0.5 hover:border-slate-700/80 hover:bg-slate-900/80"
            >
              <div className="flex items-center justify-between gap-2">
                <span className={clsx('rounded-xl bg-slate-900/85 p-2', metric.activeClass)}>
                  <Icon className="h-3.5 w-3.5" />
                </span>
                <span className="font-mono text-lg text-slate-100">
                  {metric.count}
                </span>
              </div>
              <div className="mt-3 text-[11px] uppercase tracking-[0.16em] text-slate-500">
                {metric.label}
              </div>
            </button>
          )
        })}
      </div>

      <div className="mt-5 flex flex-wrap items-center gap-2">
        <Link
          href={`/projects/${project.id}/settings`}
          className="inline-flex items-center gap-1.5 rounded-full border border-slate-700/60 bg-slate-900/70 px-3 py-1.5 text-xs text-slate-300 transition-all hover:border-slate-500 hover:text-slate-100"
        >
          <Settings2 className="h-3.5 w-3.5" />
          Settings
        </Link>
        <a
          href={project.base_url}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1.5 rounded-full border border-slate-700/60 bg-slate-900/70 px-3 py-1.5 text-xs text-slate-300 transition-all hover:border-slate-500 hover:text-slate-100"
        >
          <ExternalLink className="h-3.5 w-3.5" />
          Open app
        </a>
        <span className="ml-auto flex items-center gap-1 font-mono text-[11px] text-slate-600">
          <Clock className="h-3 w-3" />
          {new Date(project.created_at).toLocaleDateString('en-US', {
            month: 'short',
            day: 'numeric',
          })}
        </span>
      </div>
    </article>
  )
}
