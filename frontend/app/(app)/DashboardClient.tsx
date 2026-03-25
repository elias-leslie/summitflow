'use client'

import clsx from 'clsx'
import { useQuery } from '@tanstack/react-query'
import {
  AlertCircle,
  Archive,
  ArrowRight,
  Boxes,
  Bug,
  ChevronLeft,
  ChevronRight,
  FolderKanban,
  GitBranch,
  ListTodo,
  Plus,
  StickyNote,
  Target,
} from 'lucide-react'
import { motion } from 'motion/react'
import Link from 'next/link'
import { useState } from 'react'
import { ActivityFeed, ProjectCard, SystemHealthWidget } from '@/components/dashboard'
import { Skeleton } from '@/components/ui/skeleton'
import { useClampedPagination } from '@/hooks/useClampedPagination'
import { fetchProjectsWithStats, type ProjectWithStats } from '@/lib/api'

const PROJECTS_PER_PAGE = 9

const fadeUp = {
  initial: { opacity: 0, y: 14 },
  animate: { opacity: 1, y: 0 },
}

export function DashboardClient() {
  const [page, setPage] = useState(0)

  const { data, isLoading, error } = useQuery({
    queryKey: ['projects-with-stats'],
    queryFn: fetchProjectsWithStats,
  })

  const projects = data?.projects ?? []
  const totalProjects = data?.total ?? projects.length
  const totals = projects.reduce(
    (acc, p) => {
      acc.features += p.stats.features
      acc.tasks += p.stats.tasks
      acc.bugs += p.stats.bugs
      acc.blocked += p.stats.blocked
      return acc
    },
    { features: 0, tasks: 0, bugs: 0, blocked: 0 },
  )
  const totalPages = useClampedPagination({
    page,
    setPage,
    totalCount: totalProjects,
    pageSize: PROJECTS_PER_PAGE,
  })
  const startIndex = page * PROJECTS_PER_PAGE
  const endIndex = startIndex + PROJECTS_PER_PAGE
  const visibleProjects = projects.slice(startIndex, endIndex)

  const handlePrevPage = () => setPage((p) => Math.max(0, p - 1))
  const handleNextPage = () => setPage((p) => Math.min(totalPages - 1, p + 1))

  const stats = [
    { label: 'Projects', value: totalProjects, icon: FolderKanban, color: 'text-slate-100', iconColor: 'text-phosphor-500', iconBg: 'bg-phosphor-500/10' },
    { label: 'Features', value: totals.features, icon: Target, color: 'text-slate-100', iconColor: 'text-blue-400', iconBg: 'bg-blue-500/10' },
    { label: 'Tasks', value: totals.tasks, icon: ListTodo, color: 'text-slate-100', iconColor: 'text-purple-400', iconBg: 'bg-purple-500/10' },
    { label: 'Bugs', value: totals.bugs, icon: Bug, color: totals.bugs > 0 ? 'text-amber-300' : 'text-slate-100', iconColor: 'text-amber-400', iconBg: 'bg-amber-500/10' },
    { label: 'Blocked', value: totals.blocked, icon: AlertCircle, color: totals.blocked > 0 ? 'text-rose-300' : 'text-slate-100', iconColor: 'text-rose-400', iconBg: 'bg-rose-500/10' },
  ]

  const quickLinks = [
    { href: '/git', label: 'Git', sub: 'Repos, worktrees, branch hygiene', icon: GitBranch, hoverBorder: 'hover:border-violet-500/40', hoverBg: 'hover:bg-violet-500/5', iconColor: 'text-violet-400', iconBg: 'bg-violet-500/10' },
    { href: '/backups', label: 'Backups', sub: 'Snapshot readiness and drills', icon: Archive, hoverBorder: 'hover:border-indigo-500/40', hoverBg: 'hover:bg-indigo-500/5', iconColor: 'text-indigo-400', iconBg: 'bg-indigo-500/10' },
    { href: '/feedback', label: 'Feedback', sub: 'Agent friction and praise signals', icon: AlertCircle, hoverBorder: 'hover:border-amber-500/40', hoverBg: 'hover:bg-amber-500/5', iconColor: 'text-amber-400', iconBg: 'bg-amber-500/10' },
    { href: '/runtime', label: 'Runtime', sub: 'Native services and infra health', icon: Boxes, hoverBorder: 'hover:border-cyan-500/40', hoverBg: 'hover:bg-cyan-500/5', iconColor: 'text-cyan-400', iconBg: 'bg-cyan-500/10' },
  ]

  return (
    <div className="mx-auto max-w-[1500px] space-y-3 px-4 py-3 md:px-5 lg:px-6">
      <motion.section
        {...fadeUp}
        transition={{ duration: 0.4, ease: [0.25, 0.46, 0.45, 0.94] }}
        className="space-y-3"
      >
        <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
          <div className="flex items-center gap-3">
            <FolderKanban className="h-5 w-5 text-phosphor-400" />
            <div>
              <h1 className="display text-xl font-bold tracking-tight text-slate-50">
                Command Center
              </h1>
              <p className="text-sm text-slate-400">
                {totalProjects} projects &middot; {new Date().toLocaleDateString('en-US', {
                  weekday: 'short',
                  month: 'short',
                  day: 'numeric',
                })}
              </p>
            </div>
          </div>

          <div className="flex flex-wrap gap-2">
            <Link
              href="/projects/new"
              className="btn-primary inline-flex items-center gap-2 px-3 py-1.5 text-sm"
            >
              <Plus className="h-3.5 w-3.5" />
              Add Project
            </Link>
            <Link
              href="/notes"
              className="btn-secondary inline-flex items-center gap-2 px-3 py-1.5 text-sm"
            >
              <StickyNote className="h-3.5 w-3.5" />
              Notes
            </Link>
          </div>
        </div>

        <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-5">
          {stats.map((stat, i) => {
            const Icon = stat.icon
            return (
              <motion.div
                key={stat.label}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3, delay: i * 0.03, ease: [0.25, 0.46, 0.45, 0.94] }}
                className="rounded-lg border border-slate-800/80 bg-slate-950/72 px-3 py-2"
              >
                <div className="flex items-center gap-2.5">
                  <Icon className={clsx('h-3.5 w-3.5', stat.iconColor)} />
                  <div className="min-w-0 flex items-baseline gap-2">
                    <span className={clsx('font-mono text-lg font-bold leading-none tabular-nums', stat.color)}>
                      {stat.value.toLocaleString()}
                    </span>
                    <span className="text-[10px] uppercase tracking-[0.14em] text-slate-500">
                      {stat.label}
                    </span>
                  </div>
                </div>
              </motion.div>
            )
          })}
        </div>
      </motion.section>

      <div className="grid gap-3 xl:grid-cols-[minmax(0,1.35fr)_340px]">
        <motion.section
          {...fadeUp}
          transition={{ duration: 0.4, delay: 0.08, ease: [0.25, 0.46, 0.45, 0.94] }}
          className="space-y-3"
        >
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h2 className="display text-sm font-semibold uppercase tracking-[0.16em] text-slate-300">
                Projects
              </h2>
              <p className="mt-0.5 text-xs text-slate-500">
                Ownership, quality, and service readiness
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {totalPages > 1 && (
                <div className="flex items-center gap-1.5 rounded-full border border-slate-700/60 bg-slate-900/70 px-2.5 py-1 text-xs">
                  <span className="text-slate-500">
                    {Math.min(startIndex + 1, totalProjects)}-
                    {Math.min(endIndex, totalProjects)} of {totalProjects}
                  </span>
                  <button
                    type="button"
                    onClick={handlePrevPage}
                    disabled={page === 0}
                    className="rounded-full p-0.5 text-slate-400 transition-colors hover:bg-slate-800 hover:text-slate-100 disabled:cursor-not-allowed disabled:opacity-30"
                    aria-label="Previous page"
                  >
                    <ChevronLeft className="h-3.5 w-3.5" />
                  </button>
                  <span className="font-mono text-slate-500">
                    {page + 1}/{totalPages}
                  </span>
                  <button
                    type="button"
                    onClick={handleNextPage}
                    disabled={page === totalPages - 1}
                    className="rounded-full p-0.5 text-slate-400 transition-colors hover:bg-slate-800 hover:text-slate-100 disabled:cursor-not-allowed disabled:opacity-30"
                    aria-label="Next page"
                  >
                    <ChevronRight className="h-3.5 w-3.5" />
                  </button>
                </div>
              )}
              <Link
                href="/projects/new"
                className="btn-primary inline-flex items-center gap-1.5 px-3 py-1.5 text-xs"
              >
                <Plus className="h-3.5 w-3.5" />
                Add Project
              </Link>
            </div>
          </div>
          <ProjectsGrid
            projects={visibleProjects}
            isLoading={isLoading}
            error={error}
          />
        </motion.section>

        <div className="space-y-3">
          <motion.section
            {...fadeUp}
            transition={{ duration: 0.4, delay: 0.12, ease: [0.25, 0.46, 0.45, 0.94] }}
            className="panel-glass p-3"
          >
            <div className="flex items-center justify-between gap-2 mb-2">
              <h2 className="display text-sm font-semibold uppercase tracking-[0.16em] text-slate-300">
                Platform health
              </h2>
              <span className="rounded-full border border-phosphor-500/16 bg-phosphor-500/10 px-2 py-0.5 text-[10px] uppercase tracking-[0.14em] text-phosphor-300">
                Live
              </span>
            </div>
            <SystemHealthWidget />
            <div className="mt-3 grid gap-2 sm:grid-cols-2">
              {quickLinks.map((link) => {
                const Icon = link.icon

                return (
                  <Link
                    key={link.href}
                    href={link.href}
                    className={clsx(
                      'group/link rounded-lg border border-slate-800/70 bg-slate-950/72 px-2.5 py-2 transition-colors',
                      link.hoverBorder,
                      link.hoverBg,
                    )}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <Icon className={clsx('h-3.5 w-3.5', link.iconColor)} />
                        <div>
                          <div className="text-xs font-medium text-slate-100">
                            {link.label}
                          </div>
                          <div className="text-[10px] text-slate-500">
                            {link.sub}
                          </div>
                        </div>
                      </div>
                      <ArrowRight className="h-3 w-3 text-slate-700 transition-transform duration-200 group-hover/link:translate-x-0.5" />
                    </div>
                  </Link>
                )
              })}
            </div>
          </motion.section>

          <motion.section
            {...fadeUp}
            transition={{ duration: 0.4, delay: 0.16, ease: [0.25, 0.46, 0.45, 0.94] }}
            className="space-y-2"
          >
            <h2 className="display text-sm font-semibold uppercase tracking-[0.16em] text-slate-300">
              Recent activity
            </h2>
            <ActivityFeed />
          </motion.section>
        </div>
      </div>
    </div>
  )
}

interface ProjectsGridProps {
  projects: ProjectWithStats[]
  isLoading: boolean
  error: Error | null
}

function ProjectsGrid({
  projects,
  isLoading,
  error,
}: ProjectsGridProps) {
  if (isLoading) {
    return (
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="card p-5 space-y-4">
            <div className="flex items-center gap-3">
              <Skeleton className="w-12 h-12 rounded-xl" />
              <div className="space-y-2 flex-1">
                <Skeleton className="h-4 w-3/4 rounded" />
                <Skeleton className="h-3 w-1/2 rounded" />
              </div>
            </div>
            <Skeleton className="h-px w-full" />
            <div className="flex items-center gap-3">
              <Skeleton className="h-6 w-12 rounded" />
              <Skeleton className="h-6 w-12 rounded" />
              <Skeleton className="h-6 w-12 rounded" />
            </div>
          </div>
        ))}
      </div>
    )
  }

  if (error) {
    return (
      <div className="panel-glass p-8 text-center">
        <AlertCircle className="w-8 h-8 text-rose-500 mx-auto mb-2" />
        <p className="text-slate-400">Failed to load projects</p>
        <p className="text-xs text-rose-400 mono mt-1">{String(error)}</p>
      </div>
    )
  }

  if (!projects.length) {
    return (
      <div className="panel-glass border-dashed p-10 text-center">
        <FolderKanban className="w-10 h-10 text-slate-600 mx-auto mb-3" />
        <p className="text-slate-400 mb-1">No projects registered</p>
        <p className="text-sm text-slate-500 mb-4">
          Add your first project to start tracking health, quality, tasks, and automation
        </p>
        <Link
          href="/projects/new"
          className="btn-primary inline-flex items-center gap-2"
        >
          <Plus className="w-4 h-4" />
          Add Project
        </Link>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
        {projects.map((project, i) => (
          <motion.div
            key={project.id}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.35, delay: i * 0.06, ease: [0.25, 0.46, 0.45, 0.94] }}
          >
            <ProjectCard project={project} />
          </motion.div>
        ))}
      </div>
    </div>
  )
}
