'use client'

import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import {
  AlertCircle,
  Bug,
  ChevronLeft,
  ChevronRight,
  FolderKanban,
  ListTodo,
  Plus,
  Target,
} from 'lucide-react'
import { motion } from 'motion/react'
import Link from 'next/link'
import { useState } from 'react'
import { ActivityFeed, ProjectCard } from '@/components/dashboard'
import { ProjectCardGridSkeleton } from '@/components/projects/ProjectCardGridSkeleton'
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
    {
      label: 'Projects',
      value: totalProjects,
      icon: FolderKanban,
      color: 'text-slate-100',
      iconColor: 'text-phosphor-500',
      iconBg: 'bg-phosphor-500/10',
    },
    {
      label: 'Features',
      value: totals.features,
      icon: Target,
      color: 'text-slate-100',
      iconColor: 'text-blue-400',
      iconBg: 'bg-blue-500/10',
    },
    {
      label: 'Tasks',
      value: totals.tasks,
      icon: ListTodo,
      color: 'text-slate-100',
      iconColor: 'text-purple-400',
      iconBg: 'bg-purple-500/10',
    },
    {
      label: 'Bugs',
      value: totals.bugs,
      icon: Bug,
      color: totals.bugs > 0 ? 'text-amber-300' : 'text-slate-100',
      iconColor: 'text-amber-400',
      iconBg: 'bg-amber-500/10',
    },
    {
      label: 'Blocked',
      value: totals.blocked,
      icon: AlertCircle,
      color: totals.blocked > 0 ? 'text-rose-300' : 'text-slate-100',
      iconColor: 'text-rose-400',
      iconBg: 'bg-rose-500/10',
    },
  ]

  return (
    <div className="p-6 space-y-6 max-w-[1440px]">
      {/* Stats Strip */}
      <motion.div
        {...fadeUp}
        transition={{
          duration: 0.4,
          delay: 0.04,
          ease: [0.25, 0.46, 0.45, 0.94],
        }}
      >
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
          {stats.map((stat, i) => {
            const Icon = stat.icon
            return (
              <motion.div
                key={stat.label}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{
                  duration: 0.35,
                  delay: 0.06 + i * 0.05,
                  ease: [0.25, 0.46, 0.45, 0.94],
                }}
                className="card px-5 py-4 flex items-center gap-4 relative overflow-hidden"
              >
                <div
                  className={clsx(
                    'rounded-xl p-3 ring-1 ring-white/5',
                    stat.iconBg,
                  )}
                >
                  <Icon className={clsx('w-5 h-5', stat.iconColor)} />
                </div>
                <div>
                  <div
                    className={clsx(
                      'text-[28px] font-extrabold tabular-nums leading-none tracking-tight',
                      stat.color,
                    )}
                  >
                    {stat.value}
                  </div>
                  <div className="text-2xs text-slate-500 mt-1.5 font-medium uppercase tracking-wider">
                    {stat.label}
                  </div>
                </div>
              </motion.div>
            )
          })}
        </div>
      </motion.div>

      {/* Projects */}
      <motion.section
        {...fadeUp}
        transition={{
          duration: 0.4,
          delay: 0.1,
          ease: [0.25, 0.46, 0.45, 0.94],
        }}
      >
        <div className="flex items-center justify-between mb-4">
          <h2 className="display font-bold text-xl text-slate-100 tracking-tight">
            Projects
          </h2>
          <div className="flex items-center gap-3">
            {totalPages > 1 && (
              <div className="flex items-center gap-1.5 text-xs">
                <span className="text-slate-500">
                  {Math.min(startIndex + 1, totalProjects)}-
                  {Math.min(endIndex, totalProjects)} of {totalProjects}
                </span>
                <button
                  type="button"
                  onClick={handlePrevPage}
                  disabled={page === 0}
                  className="p-1 rounded text-slate-400 hover:text-slate-100 hover:bg-slate-800 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                  aria-label="Previous page"
                >
                  <ChevronLeft className="w-3.5 h-3.5" />
                </button>
                <span className="text-slate-500 tabular-nums">
                  {page + 1}/{totalPages}
                </span>
                <button
                  type="button"
                  onClick={handleNextPage}
                  disabled={page === totalPages - 1}
                  className="p-1 rounded text-slate-400 hover:text-slate-100 hover:bg-slate-800 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                  aria-label="Next page"
                >
                  <ChevronRight className="w-3.5 h-3.5" />
                </button>
              </div>
            )}
            <Link
              href="/projects/new"
              className="btn-primary text-xs flex items-center gap-1.5 px-3 py-1.5"
            >
              <Plus className="w-3.5 h-3.5" />
              Add
            </Link>
          </div>
        </div>
        <ProjectsGrid
          projects={visibleProjects}
          isLoading={isLoading}
          error={error}
        />
      </motion.section>

      {/* Activity */}
      <motion.section
        {...fadeUp}
        transition={{
          duration: 0.4,
          delay: 0.14,
          ease: [0.25, 0.46, 0.45, 0.94],
        }}
      >
        <div className="mb-4">
          <h2 className="display font-bold text-lg text-slate-100 tracking-tight">
            Recent Activity
          </h2>
          <div className="chrome-line mt-2" />
        </div>
        <ActivityFeed />
      </motion.section>
    </div>
  )
}

interface ProjectsGridProps {
  projects: ProjectWithStats[]
  isLoading: boolean
  error: Error | null
}

function ProjectsGrid({ projects, isLoading, error }: ProjectsGridProps) {
  if (isLoading) {
    return <ProjectCardGridSkeleton />
  }

  if (error) {
    return (
      <div className="card p-8 text-center">
        <AlertCircle className="w-8 h-8 text-rose-500 mx-auto mb-2" />
        <p className="text-slate-400">Failed to load projects</p>
        <p className="text-xs text-rose-400 mono mt-1">{String(error)}</p>
      </div>
    )
  }

  if (!projects.length) {
    return (
      <div className="card p-8 text-center border-dashed">
        <FolderKanban className="w-10 h-10 text-slate-600 mx-auto mb-3" />
        <p className="text-slate-400 mb-1">No projects registered</p>
        <p className="text-sm text-slate-500 mb-4">
          Add your first project to start tracking health, quality, tasks, and
          automation
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
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {projects.map((project, i) => (
          <motion.div
            key={project.id}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{
              duration: 0.35,
              delay: i * 0.06,
              ease: [0.25, 0.46, 0.45, 0.94],
            }}
          >
            <ProjectCard project={project} />
          </motion.div>
        ))}
      </div>
    </div>
  )
}
