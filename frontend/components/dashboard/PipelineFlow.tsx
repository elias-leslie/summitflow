'use client'

import { useQuery } from '@tanstack/react-query'
import { fetchTasks } from '@/lib/api'

interface PipelineStage {
  label: string
  count: number
  color: string
}

interface PipelineFlowProps {
  projectId: string
  onStageClick?: (phase: string) => void
}

export function PipelineFlow({ projectId, onStageClick }: PipelineFlowProps) {
  const { data } = useQuery({
    queryKey: ['tasks', projectId, 'all'],
    queryFn: () => fetchTasks(projectId, { limit: 500 }),
    staleTime: 30000,
  })

  const tasks = data?.tasks ?? []
  const isCrowdsourced = (t: { labels?: string[] }) =>
    t.labels?.some((l) => l.toLowerCase() === 'crowdsourced')

  const stages: PipelineStage[] = [
    {
      label: 'Ideation',
      count: tasks.filter(
        (t) => t.status === 'pending' && isCrowdsourced(t),
      ).length,
      color: 'bg-yellow-500',
    },
    {
      label: 'Planning',
      count: tasks.filter(
        (t) => t.status === 'pending' && !isCrowdsourced(t),
      ).length,
      color: 'bg-slate-500',
    },
    {
      label: 'Queued',
      count: tasks.filter((t) => t.status === 'queue').length,
      color: 'bg-sky-500',
    },
    {
      label: 'Executing',
      count: tasks.filter(
        (t) => t.status === 'running' || t.status === 'paused',
      ).length,
      color: 'bg-blue-500',
    },
    {
      label: 'QA Review',
      count: tasks.filter((t) => t.status === 'ai_reviewing').length,
      color: 'bg-violet-500',
    },
    {
      label: 'Done',
      count: tasks.filter((t) => t.status === 'completed').length,
      color: 'bg-phosphor-500',
    },
  ]

  const phaseKeys = [
    'ideation',
    'planning',
    'queue',
    'executing',
    'reviewing',
    'completed',
  ]

  return (
    <div className="flex items-center gap-1">
      {stages.map((stage, i) => (
        <div key={stage.label} className="flex items-center">
          <button
            onClick={() => onStageClick?.(phaseKeys[i])}
            className="flex flex-col items-center px-3 py-2 rounded-lg hover:bg-slate-800/50 transition-colors min-w-[72px]"
          >
            <div
              className={`w-8 h-8 rounded-full ${stage.color} flex items-center justify-center text-xs font-bold text-white`}
            >
              {stage.count}
            </div>
            <span className="text-[10px] text-slate-400 mt-1">
              {stage.label}
            </span>
          </button>
          {i < stages.length - 1 && (
            <div className="w-4 h-px bg-slate-700" />
          )}
        </div>
      ))}
    </div>
  )
}
