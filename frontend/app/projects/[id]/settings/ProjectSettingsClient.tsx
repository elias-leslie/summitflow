'use client'

import { useQuery } from '@tanstack/react-query'
import {
  AlertCircle,
  ArrowLeft,
  ExternalLink,
  Loader2,
  Link2,
  FolderTree,
  Settings2,
} from 'lucide-react'
import Link from 'next/link'
import { useParams } from 'next/navigation'
import { AutonomousSettingsPanel } from '@/components/settings/AutonomousSettings'
import { fetchProject } from '@/lib/api'
import { getErrorMessage } from '@/lib/utils'

export function ProjectSettingsClient() {
  const params = useParams()
  const projectId = params.id as string

  const {
    data: project,
    isLoading: projectLoading,
    error,
  } = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => fetchProject(projectId),
  })

  if (projectLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-8 h-8 animate-spin text-slate-400" />
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

  return (
    <main className="content-container py-8">
      <header className="mb-8">
        <div className="flex items-center gap-4">
          <Link
            href={`/projects/${projectId}`}
            className="text-slate-400 hover:text-slate-200 transition-colors"
          >
            <ArrowLeft className="w-5 h-5" />
          </Link>
          <div>
            <h1 className="text-2xl font-semibold text-slate-100 flex items-center gap-3">
              <Settings2 className="w-6 h-6 text-slate-400" />
              Project Settings
            </h1>
            <p className="text-sm text-slate-400 mt-1">{project.name}</p>
          </div>
        </div>
      </header>

      <section className="mb-6 grid gap-4 md:grid-cols-3">
        <div className="card rounded-xl p-4">
          <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-slate-500">
            <Link2 className="h-3.5 w-3.5" />
            Project ID
          </div>
          <div className="mt-2 font-mono text-sm text-slate-200">{project.id}</div>
        </div>
        <div className="card rounded-xl p-4">
          <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-slate-500">
            <ExternalLink className="h-3.5 w-3.5" />
            Base URL
          </div>
          <a
            href={project.base_url}
            target="_blank"
            rel="noreferrer"
            className="mt-2 block break-all text-sm text-phosphor-400 hover:text-phosphor-300"
          >
            {project.base_url}
          </a>
        </div>
        <div className="card rounded-xl p-4">
          <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-slate-500">
            <FolderTree className="h-3.5 w-3.5" />
            Root Path
          </div>
          <div className="mt-2 break-all font-mono text-sm text-slate-300">
            {project.root_path ?? 'Not configured'}
          </div>
        </div>
      </section>

      <section className="animate-fade-in">
        <div className="max-w-xl">
          <p className="mb-4 text-sm text-slate-400">
            Control autonomous execution, quality-gate behavior, and merge posture for{' '}
            <span className="text-slate-200">{project.name}</span>.
          </p>
          <AutonomousSettingsPanel projectId={projectId} />
        </div>
      </section>
    </main>
  )
}
