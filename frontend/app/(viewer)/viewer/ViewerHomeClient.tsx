'use client'

import { useQuery } from '@tanstack/react-query'
import { Eye, Loader2, Palette } from 'lucide-react'
import Link from 'next/link'
import { fetchAuthMe } from '@/lib/api/auth'
import { fetchViewerProjects } from '@/lib/api/viewer'

export function ViewerHomeClient(): React.ReactElement {
  const { data: me, isLoading: authLoading } = useQuery({
    queryKey: ['auth-me'],
    queryFn: fetchAuthMe,
    retry: false,
  })
  const { data: projects, isLoading: projectsLoading } = useQuery({
    queryKey: ['viewer-projects'],
    queryFn: fetchViewerProjects,
    enabled: Boolean(me?.is_viewer),
  })

  if (authLoading || projectsLoading) {
    return (
      <div className="flex h-full items-center justify-center text-slate-400">
        <Loader2 className="mr-2 h-5 w-5 animate-spin" />
        Loading shared workspace...
      </div>
    )
  }

  if (!me?.is_viewer) {
    return (
      <main className="mx-auto flex h-full w-full max-w-3xl items-center justify-center p-6">
        <div className="card p-8 text-center">
          <Eye className="mx-auto mb-4 h-10 w-10 text-slate-500" />
          <h1 className="display text-xl font-semibold text-slate-100">
            Viewer access is not enabled
          </h1>
          <p className="mt-2 text-sm text-slate-400">
            Ask the SummitFlow owner to add your authenticated email to sharing.
          </p>
        </div>
      </main>
    )
  }

  return (
    <main className="mx-auto w-full max-w-5xl flex-1 overflow-auto p-6">
      <header className="mb-6 rounded-[28px] border border-slate-800 bg-slate-950/70 p-6">
        <p className="text-xs uppercase tracking-[0.24em] text-cyan-300">
          SummitFlow Viewer
        </p>
        <h1 className="display mt-3 text-3xl font-bold text-slate-100">
          Shared project design work
        </h1>
        <p className="mt-2 text-sm text-slate-400">
          Signed in as <span className="font-mono">{me.email}</span>. This space
          is read-only.
        </p>
      </header>

      {projects?.length ? (
        <div className="grid gap-4 md:grid-cols-2">
          {projects.map((project) => (
            <Link
              key={project.id}
              href={`/viewer/projects/${project.id}/design`}
              className="card group p-5 transition hover:border-cyan-500/40 hover:bg-slate-900/80"
            >
              <div className="flex items-start gap-3">
                <div className="rounded-2xl bg-fuchsia-500/10 p-3 ring-1 ring-fuchsia-400/20">
                  <Palette className="h-5 w-5 text-fuchsia-300" />
                </div>
                <div className="min-w-0">
                  <h2 className="truncate text-lg font-semibold text-slate-100">
                    {project.name}
                  </h2>
                  <p className="mt-1 font-mono text-xs text-slate-500">
                    {project.id}
                  </p>
                  <p className="mt-3 text-sm text-slate-400">
                    Shared sections: {project.sections.join(', ')}
                  </p>
                </div>
              </div>
            </Link>
          ))}
        </div>
      ) : (
        <div className="card p-8 text-center text-slate-400">
          No projects have been shared with this viewer yet.
        </div>
      )}
    </main>
  )
}
