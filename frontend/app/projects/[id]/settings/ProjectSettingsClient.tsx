'use client'

import { useQuery } from '@tanstack/react-query'
import {
  ArrowLeft,
  Loader2,
  Settings2,
} from 'lucide-react'
import Link from 'next/link'
import { useParams } from 'next/navigation'
import { AutonomousSettingsPanel } from '@/components/settings/AutonomousSettings'
import { fetchProject } from '@/lib/api'

export function ProjectSettingsClient() {
  const params = useParams()
  const projectId = params.id as string

  const { data: project, isLoading: projectLoading } = useQuery({
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

  if (!project) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-4">
        <p className="text-slate-400">Project not found</p>
        <Link href="/" className="text-blue-400 hover:text-blue-300">
          Back to dashboard
        </Link>
      </div>
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

      <section className="animate-fade-in">
        <div className="max-w-xl">
          <AutonomousSettingsPanel projectId={projectId} />
        </div>
      </section>
    </main>
  )
}
