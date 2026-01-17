'use client'

import clsx from 'clsx'
import {
  Activity,
  CheckCircle2,
  FileSearch,
  GitBranch,
  MessageSquare,
  Target,
} from 'lucide-react'

type ActivityType =
  | 'task_complete'
  | 'file_scanned'
  | 'feature_updated'
  | 'health_check'
  | 'commit'
  | 'chat'

interface ActivityItem {
  id: string
  type: ActivityType
  message: string
  time: string
  project?: string
}

const activityIcons: Record<
  ActivityType,
  { icon: React.ElementType; color: string }
> = {
  task_complete: {
    icon: CheckCircle2,
    color: 'text-green-400 bg-green-500/10',
  },
  file_scanned: { icon: FileSearch, color: 'text-blue-400 bg-blue-500/10' },
  feature_updated: { icon: Target, color: 'text-amber-400 bg-amber-500/10' },
  health_check: { icon: Activity, color: 'text-purple-400 bg-purple-500/10' },
  commit: { icon: GitBranch, color: 'text-cyan-400 bg-cyan-500/10' },
  chat: { icon: MessageSquare, color: 'text-pink-400 bg-pink-500/10' },
}

interface ActivityFeedProps {
  className?: string
}

export function ActivityFeed({ className }: ActivityFeedProps) {
  // Placeholder activity data
  // In production, this would come from an API endpoint
  const activities: ActivityItem[] = [
    {
      id: '1',
      type: 'health_check',
      message: 'Health check passed for SummitFlow',
      time: '2 min ago',
      project: 'summitflow',
    },
    {
      id: '2',
      type: 'task_complete',
      message: 'System initialized successfully',
      time: 'Just now',
    },
  ]

  if (activities.length === 0) {
    return (
      <div className={clsx('card p-8 text-center', className)}>
        <Activity className="w-10 h-10 text-slate-600 mx-auto mb-3" />
        <p className="text-sm text-slate-500">No recent activity</p>
        <p className="text-xs text-slate-600 mt-1">
          Activity will appear here as you use SummitFlow
        </p>
      </div>
    )
  }

  return (
    <div className={clsx('card divide-y divide-slate-800', className)}>
      {activities.map((activity) => {
        const { icon: Icon, color } = activityIcons[activity.type]

        return (
          <div
            key={activity.id}
            className="p-4 flex items-center gap-4 hover:bg-slate-800/30 transition-colors cursor-pointer"
          >
            <div className={clsx('p-2 rounded-lg', color.split(' ')[1])}>
              <Icon className={clsx('w-4 h-4', color.split(' ')[0])} />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm text-slate-300 truncate">
                {activity.message}
              </p>
              {activity.project && (
                <p className="text-xs text-slate-500 mono mt-0.5">
                  {activity.project}
                </p>
              )}
            </div>
            <span className="text-xs text-slate-500 mono flex-shrink-0">
              {activity.time}
            </span>
          </div>
        )
      })}

      {/* Show hint if only placeholder data */}
      {activities.length <= 2 && (
        <div className="p-4 text-center">
          <p className="text-xs text-slate-500">
            More activity will appear as you use SummitFlow
          </p>
        </div>
      )}
    </div>
  )
}
