'use client'

import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { AlertCircle, Bug, Clock, ListTodo, Target } from 'lucide-react'
import Image from 'next/image'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useState } from 'react'
import {
  fetchProjectHealth,
  fetchQualityGateHealth,
  type ProjectWithStats,
} from '@/lib/api'

interface ProjectCardProps {
  project: ProjectWithStats
}

export function ProjectCard({ project }: ProjectCardProps) {
  const router = useRouter()
  const [showHealth, setShowHealth] = useState(false)

  const { data: health, isLoading: healthLoading } = useQuery({
    queryKey: ['project-health', project.id],
    queryFn: () => fetchProjectHealth(project.id),
    enabled: showHealth,
    refetchInterval: showHealth ? 30000 : false,
  })

  const { data: qualityGate, isLoading: qualityLoading } = useQuery({
    queryKey: ['quality-gate-health', project.id],
    queryFn: () => fetchQualityGateHealth(project.id),
    enabled: showHealth,
    refetchInterval: showHealth ? 30000 : false,
  })

  // Generate gradient based on first letter (used as fallback if no logo)
  const gradients: Record<string, { from: string; to: string }> = {
    S: { from: '#00c853', to: '#009624' },
    P: { from: '#3b82f6', to: '#2563eb' },
    A: { from: '#8b5cf6', to: '#6d28d9' },
    C: { from: '#f59e0b', to: '#d97706' },
    B: { from: '#ec4899', to: '#be185d' },
    D: { from: '#06b6d4', to: '#0891b2' },
    default: { from: '#64748b', to: '#475569' },
  }
  const firstLetter = project.name.charAt(0).toUpperCase()
  const gradient = gradients[firstLetter] ?? gradients.default

  const { stats } = project

  // Handle stat click - navigate to project with appropriate tab/filter
  const handleStatClick = (
    e: React.MouseEvent,
    type: 'features' | 'tasks' | 'bugs' | 'blocked',
  ) => {
    e.preventDefault()
    e.stopPropagation()

    switch (type) {
      case 'features':
        router.push(`/projects/${project.id}?tab=features`)
        break
      case 'tasks':
        // Show active non-bug tasks (matches dashboard count)
        router.push(`/projects/${project.id}?tab=tasks&status=active`)
        break
      case 'bugs':
        // Show active bugs only (matches dashboard count)
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
    <Link
      href={`/projects/${project.id}`}
      className={clsx(
        'card-elevated p-5 group transition-all duration-300',
        'hover:border-phosphor-500/50 hover:translate-y-[-2px]',
      )}
      onMouseEnter={() => setShowHealth(true)}
    >
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-3">
          {/* Project avatar - logo or fallback to gradient letter */}
          {project.logo_url ? (
            <div className="w-12 h-12 rounded-xl overflow-hidden bg-slate-800 flex items-center justify-center">
              <Image
                src={project.logo_url}
                alt={project.name}
                width={48}
                height={48}
                className="object-cover w-full h-full"
              />
            </div>
          ) : (
            <div
              className="w-12 h-12 rounded-xl flex items-center justify-center"
              style={{
                background: `linear-gradient(135deg, ${gradient.from} 0%, ${gradient.to} 100%)`,
              }}
            >
              <span className="display font-bold text-xl text-white">
                {firstLetter}
              </span>
            </div>
          )}
          <div>
            <h3 className="font-medium text-white group-hover:text-phosphor-400 transition-colors">
              {project.name}
            </h3>
            <p className="text-xs mono text-slate-500 truncate max-w-[160px]">
              {project.base_url}
            </p>
          </div>
        </div>

        {/* Health status with glow */}
        <div className="flex items-center gap-2">
          {/* Quality gate indicator */}
          {qualityLoading ? (
            <div className="w-3 h-3 border border-slate-600 border-t-purple-500 rounded-full animate-spin" />
          ) : qualityGate ? (
            <div
              className={clsx(
                'w-3 h-3 rounded-full',
                qualityGate.overall_pass
                  ? 'bg-purple-500 shadow-[0_0_8px_rgba(168,85,247,0.6)]'
                  : 'bg-amber-500 shadow-[0_0_8px_rgba(245,158,11,0.6)]',
              )}
              title={
                qualityGate.overall_pass
                  ? 'Quality gate passing'
                  : `Quality gate: ${qualityGate.total_unfixed} unfixed issues`
              }
              data-testid="quality-gate-indicator"
            />
          ) : (
            <div
              className="w-3 h-3 rounded-full bg-slate-700"
              data-testid="quality-gate-indicator"
            />
          )}

          {/* Service health indicator */}
          {healthLoading ? (
            <div className="w-3 h-3 border border-slate-600 border-t-phosphor-500 rounded-full animate-spin" />
          ) : health ? (
            <div
              className={clsx(
                'w-3 h-3 rounded-full',
                health.healthy
                  ? 'bg-green-500 shadow-[0_0_8px_rgba(34,197,94,0.6)]'
                  : 'bg-rose-500 shadow-[0_0_8px_rgba(244,63,94,0.6)]',
              )}
              title={health.healthy ? 'Service healthy' : `Service error: ${health.error}`}
              data-testid="project-health-indicator"
            />
          ) : (
            <div
              className="w-3 h-3 rounded-full bg-slate-600"
              data-testid="project-health-indicator"
            />
          )}
        </div>
      </div>

      {/* Stats row */}
      <div className="mt-4 pt-3 border-t border-slate-800">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            {/* Features */}
            <button
              onClick={(e) => handleStatClick(e, 'features')}
              className={clsx(
                'flex items-center gap-1 text-xs transition-colors',
                stats.features > 0
                  ? 'text-blue-400 hover:text-blue-300'
                  : 'text-slate-500 hover:text-slate-400',
              )}
              title="View features"
            >
              <Target className="w-3 h-3" />
              <span className="tabular-nums">{stats.features}</span>
            </button>

            {/* Tasks */}
            <button
              onClick={(e) => handleStatClick(e, 'tasks')}
              className={clsx(
                'flex items-center gap-1 text-xs transition-colors',
                stats.tasks > 0
                  ? 'text-purple-400 hover:text-purple-300'
                  : 'text-slate-500 hover:text-slate-400',
              )}
              title="View tasks"
            >
              <ListTodo className="w-3 h-3" />
              <span className="tabular-nums">{stats.tasks}</span>
            </button>

            {/* Bugs */}
            <button
              onClick={(e) => handleStatClick(e, 'bugs')}
              className={clsx(
                'flex items-center gap-1 text-xs transition-colors',
                stats.bugs > 0
                  ? 'text-amber-400 hover:text-amber-300'
                  : 'text-slate-500 hover:text-slate-400',
              )}
              title="View bugs"
            >
              <Bug className="w-3 h-3" />
              <span className="tabular-nums">{stats.bugs}</span>
            </button>

            {/* Blocked */}
            <button
              onClick={(e) => handleStatClick(e, 'blocked')}
              className={clsx(
                'flex items-center gap-1 text-xs transition-colors',
                stats.blocked > 0
                  ? 'text-rose-400 hover:text-rose-300'
                  : 'text-slate-500 hover:text-slate-400',
              )}
              title="View blocked"
            >
              <AlertCircle className="w-3 h-3" />
              <span className="tabular-nums">{stats.blocked}</span>
            </button>
          </div>

          <span className="text-xs text-slate-500 flex items-center gap-1">
            <Clock className="w-3 h-3" />
            {new Date(project.created_at).toLocaleDateString()}
          </span>
        </div>
      </div>
    </Link>
  )
}
