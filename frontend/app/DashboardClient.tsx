'use client'

import { useQuery } from '@tanstack/react-query'
import {
  AlertCircle,
  Archive,
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
import { ActivityFeed, ProjectCard, SystemHealthWidget } from '@/components/dashboard'
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
    { label: 'Projects', value: totalProjects, icon: FolderKanban, color: 'text-white' },
    { label: 'Features', value: totals.features, icon: Target, color: 'text-white' },
    { label: 'Tasks', value: totals.tasks, icon: ListTodo, color: 'text-white' },
    { label: 'Bugs', value: totals.bugs, icon: Bug, color: totals.bugs > 0 ? 'text-amber-300' : 'text-white' },
    { label: 'Blocked', value: totals.blocked, icon: AlertCircle, color: totals.blocked > 0 ? 'text-rose-300' : 'text-white' },
  ]

  const quickLinks = [
    { href: '/backups', label: 'Backups', sub: 'DB snapshots', icon: Archive, hoverBorder: 'hover:border-indigo-500/40', hoverBg: 'hover:bg-indigo-500/5', iconColor: 'text-indigo-400' },
    { href: '/feedback', label: 'Feedback', sub: 'Signals & fixes', icon: AlertCircle, hoverBorder: 'hover:border-amber-500/40', hoverBg: 'hover:bg-amber-500/5', iconColor: 'text-amber-400' },
  ]

  return (
    <div className="p-6 space-y-6 max-w-[1440px]">
      {/* Hero: Title + System Health */}
      <motion.div
        {...fadeUp}
        transition={{ duration: 0.4, ease: [0.25, 0.46, 0.45, 0.94] }}
        className="flex flex-col sm:flex-row sm:items-end justify-between gap-4"
      >
        <div>
          <h1 className="display text-[28px] font-extrabold text-white tracking-tight leading-none">
            Command Center
          </h1>
          <p className="mt-1.5 text-sm text-slate-500">
            {new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })}
          </p>
        </div>
        <SystemHealthWidget />
      </motion.div>

      {/* Stats Strip */}
      <motion.div
        {...fadeUp}
        transition={{ duration: 0.4, delay: 0.04, ease: [0.25, 0.46, 0.45, 0.94] }}
      >
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-px rounded-xl overflow-hidden bg-slate-800/60">
          {stats.map((stat) => {
            const Icon = stat.icon
            return (
              <div key={stat.label} className="bg-slate-900/90 px-4 py-3.5 flex items-center gap-3">
                <div className="rounded-lg bg-slate-800 p-2">
                  <Icon className="w-4 h-4 text-slate-500" />
                </div>
                <div>
                  <div className={`text-2xl font-bold tabular-nums leading-none ${stat.color}`}>
                    {stat.value}
                  </div>
                  <div className="text-[11px] text-slate-500 mt-1">{stat.label}</div>
                </div>
              </div>
            )
          })}
        </div>
      </motion.div>

      {/* Quick Links */}
      <motion.div
        {...fadeUp}
        transition={{ duration: 0.4, delay: 0.07, ease: [0.25, 0.46, 0.45, 0.94] }}
        className="flex flex-wrap items-center gap-3"
      >
        {quickLinks.map((link) => {
          const Icon = link.icon
          return (
            <Link
              key={link.href}
              href={link.href}
              className={`card px-4 py-3 flex items-center gap-3 transition-all ${link.hoverBorder} ${link.hoverBg}`}
            >
              <Icon className={`w-4 h-4 ${link.iconColor}`} />
              <div>
                <div className="text-sm font-medium text-white leading-none">{link.label}</div>
                <div className="text-[11px] text-slate-500 mt-0.5">{link.sub}</div>
              </div>
            </Link>
          )
        })}
      </motion.div>

      {/* Projects */}
      <motion.section
        {...fadeUp}
        transition={{ duration: 0.4, delay: 0.1, ease: [0.25, 0.46, 0.45, 0.94] }}
      >
        <div className="flex items-center justify-between mb-3">
          <h2 className="display font-semibold text-base text-white">Projects</h2>
          <div className="flex items-center gap-3">
            {totalPages > 1 && (
              <div className="flex items-center gap-1.5 text-xs">
                <span className="text-slate-500">
                  {Math.min(startIndex + 1, totalProjects)}-{Math.min(endIndex, totalProjects)} of {totalProjects}
                </span>
                <button
                  type="button"
                  onClick={handlePrevPage}
                  disabled={page === 0}
                  className="p-1 rounded text-slate-400 hover:text-white hover:bg-slate-800 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                  aria-label="Previous page"
                >
                  <ChevronLeft className="w-3.5 h-3.5" />
                </button>
                <span className="text-slate-500 tabular-nums">{page + 1}/{totalPages}</span>
                <button
                  type="button"
                  onClick={handleNextPage}
                  disabled={page === totalPages - 1}
                  className="p-1 rounded text-slate-400 hover:text-white hover:bg-slate-800 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
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
        transition={{ duration: 0.4, delay: 0.14, ease: [0.25, 0.46, 0.45, 0.94] }}
      >
        <h2 className="display font-semibold text-base text-white mb-3">Recent Activity</h2>
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

function ProjectsGrid({
  projects,
  isLoading,
  error,
}: ProjectsGridProps) {
  if (isLoading) {
    return (
      <div className="card p-8 text-center">
        <div className="inline-flex items-center gap-2 text-slate-400">
          <div className="w-4 h-4 border-2 border-phosphor-500/30 border-t-phosphor-500 rounded-full animate-spin" />
          Loading projects...
        </div>
      </div>
    )
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
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {projects.map((project) => (
          <ProjectCard key={project.id} project={project} />
        ))}
      </div>
    </div>
  )
}
