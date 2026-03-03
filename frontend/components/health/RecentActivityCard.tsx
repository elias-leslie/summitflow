'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { fetchActivity, type ActivityEvent } from '@/lib/api/activity'
import { useQuery } from '@tanstack/react-query'
import { formatRelativeTime } from './HealthUtils'

interface RecentActivityCardProps {
  projectId: string
}

const typeIcons: Record<string, string> = {
  task: '◆',
  session: '▶',
  backup: '◇',
  git: '●',
}

const typeColors: Record<string, string> = {
  task: 'text-phosphor-400',
  session: 'text-cyan-400',
  backup: 'text-amber-400',
  git: 'text-violet-400',
}

function ActivityRow({ event }: { event: ActivityEvent }) {
  const icon = typeIcons[event.type] ?? '○'
  const color = typeColors[event.type] ?? 'text-slate-400'

  return (
    <div className="flex items-start gap-2 py-1.5 border-b border-slate-800 last:border-0">
      <span className={`text-xs mt-0.5 ${color}`}>{icon}</span>
      <div className="flex-1 min-w-0">
        <p className="text-xs text-slate-300 truncate">{event.message}</p>
      </div>
      {event.timestamp && (
        <span className="text-xs text-slate-500 whitespace-nowrap">
          {formatRelativeTime(event.timestamp)}
        </span>
      )}
    </div>
  )
}

export function RecentActivityCard({ projectId }: RecentActivityCardProps) {
  const { data, isLoading } = useQuery({
    queryKey: ['activity', projectId],
    queryFn: () => fetchActivity({ project_id: projectId, limit: 8 }),
    refetchInterval: 30000,
  })

  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Recent Activity</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            {Array.from({ length: 4 }).map((_, i) => (
              <div
                key={i}
                className="h-5 bg-slate-800 rounded animate-pulse"
              />
            ))}
          </div>
        </CardContent>
      </Card>
    )
  }

  if (!data?.items.length) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Recent Activity</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col items-center justify-center py-6 text-center">
            <span className="text-slate-600 text-lg mb-1">○</span>
            <span className="text-xs text-slate-500">No recent activity</span>
          </div>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Recent Activity</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-0">
          {data.items.map((event, i) => (
            <ActivityRow key={`${event.type}-${event.timestamp}-${i}`} event={event} />
          ))}
        </div>
      </CardContent>
    </Card>
  )
}
