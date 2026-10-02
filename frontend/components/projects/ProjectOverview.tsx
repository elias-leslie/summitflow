'use client'

import { useQuery } from '@tanstack/react-query'
import Link from 'next/link'
import { fetchProjectReadme, type Project } from '@/lib/api'
import { STALE_STANDARD } from '@/lib/polling'
import { getErrorMessage } from '@/lib/utils'
import { ActivityFeed } from '../dashboard/ActivityFeed'
import { Button } from '../ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '../ui/card'
import { ProjectReadmeMarkdown } from './ProjectReadmeMarkdown'

interface ProjectOverviewProps {
  project: Project
}

export function ProjectOverview({ project }: ProjectOverviewProps) {
  const {
    data: readme,
    isLoading,
    error,
    refetch,
    isFetching,
  } = useQuery({
    queryKey: ['project-readme', project.id],
    queryFn: () => fetchProjectReadme(project.id),
    staleTime: STALE_STANDARD,
  })

  return (
    <div className="mx-auto w-full max-w-[1600px] space-y-6">
      <Card className="border-slate-800/80 bg-slate-950/55">
        <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-3 pb-3">
          <CardTitle className="text-base">README.md</CardTitle>
          <Link
            href={`/projects/${project.id}/files?path=README.md`}
            className="rounded text-xs text-slate-400 hover:text-phosphor-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-phosphor-500/60"
          >
            View project files
          </Link>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <p role="status" className="text-sm text-slate-400">
              Loading README.md...
            </p>
          ) : error ? (
            <div className="space-y-3">
              <p role="alert" className="break-words text-sm text-rose-300">
                {getErrorMessage(error, 'Could not load README.md.')}
              </p>
              <Button
                variant="secondary"
                size="sm"
                disabled={isFetching}
                onClick={() => void refetch()}
              >
                {isFetching ? 'Retrying...' : 'Retry'}
              </Button>
            </div>
          ) : readme?.status === 'available' ? (
            readme.content.trim() ? (
              <ProjectReadmeMarkdown
                projectId={project.id}
                content={readme.content}
              />
            ) : (
              <p className="text-sm text-slate-400">README.md is empty.</p>
            )
          ) : (
            <p className="text-sm text-slate-400">
              {readme?.status === 'missing'
                ? 'No README.md in the project root.'
                : 'README.md is unavailable.'}
            </p>
          )}
        </CardContent>
      </Card>
      <section className="space-y-3">
        <h2 className="text-base font-semibold text-slate-100">
          Recent Activity
        </h2>
        <ActivityFeed projectId={project.id} />
      </section>
    </div>
  )
}
