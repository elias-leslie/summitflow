/**
 * Issue Tasks Tab - Issue Tracking via SummitFlow Tasks API
 *
 * Displays tasks for a project with:
 * - Ready work section (unblocked tasks)
 * - Full task list with status/priority/type filters
 * - Create task modal
 * - Status updates
 */

'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Bug,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Circle,
  Clock,
  ListTodo,
  Loader2,
  Package,
  Plus,
  RefreshCw,
  Zap,
} from 'lucide-react'
import { useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  fetchReadyTasks,
  fetchTasks,
  type Task,
  type TaskStatus,
  type TaskType,
  updateTaskStatus,
} from '@/lib/api'
import { cn } from '@/lib/utils'
import { CreateTaskDialog } from './CreateTaskDialog'
import { TaskLogViewer } from './TaskLogViewer'

interface IssueTasksTabProps {
  projectId: string
}

// Priority colors and labels
const priorityConfig: Record<number, { label: string; color: string }> = {
  0: { label: 'P0', color: 'text-red-500' },
  1: { label: 'P1', color: 'text-orange-500' },
  2: { label: 'P2', color: 'text-yellow-500' },
  3: { label: 'P3', color: 'text-blue-500' },
  4: { label: 'P4', color: 'text-slate-500' },
}

// Status config
const statusConfig: Record<
  string,
  { label: string; icon: typeof Circle; color: string }
> = {
  pending: { label: 'Pending', icon: Circle, color: 'text-blue-500' },
  running: { label: 'Running', icon: Loader2, color: 'text-yellow-500' },
  paused: { label: 'Paused', icon: Clock, color: 'text-orange-500' },
  completed: {
    label: 'Completed',
    icon: CheckCircle2,
    color: 'text-green-500',
  },
  failed: { label: 'Failed', icon: Circle, color: 'text-red-500' },
}

// Type icons
const typeIcons: Record<string, typeof ListTodo> = {
  feature: Package,
  bug: Bug,
  task: ListTodo,
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return '-'
  const date = new Date(dateStr)
  const now = new Date()
  const diffDays = Math.floor(
    (now.getTime() - date.getTime()) / (1000 * 60 * 60 * 24),
  )

  if (diffDays === 0) return 'Today'
  if (diffDays === 1) return 'Yesterday'
  if (diffDays < 7) return `${diffDays}d ago`
  return date.toLocaleDateString()
}

// Task Row Component
function TaskRow({
  task,
  isExpanded,
  onToggle,
  onStatusChange,
  isUpdating,
  projectId,
}: {
  task: Task
  isExpanded: boolean
  onToggle: () => void
  onStatusChange: (status: TaskStatus) => void
  isUpdating: boolean
  projectId: string
}) {
  const priority = priorityConfig[task.priority] || priorityConfig[2]
  const status = statusConfig[task.status] || statusConfig.pending
  const TypeIcon = typeIcons[task.task_type] || ListTodo
  const StatusIcon = status.icon

  return (
    <>
      <tr
        className={cn(
          'border-b border-slate-700/50 hover:bg-slate-800/50 cursor-pointer transition-colors',
          isExpanded && 'bg-slate-800/30',
        )}
        onClick={onToggle}
      >
        {/* Expand */}
        <td className="w-8 px-2 py-2">
          {isExpanded ? (
            <ChevronDown className="w-4 h-4 text-slate-500" />
          ) : (
            <ChevronRight className="w-4 h-4 text-slate-500" />
          )}
        </td>

        {/* Priority */}
        <td className="w-12 px-2 py-2">
          <span className={cn('text-xs font-mono font-bold', priority.color)}>
            {priority.label}
          </span>
        </td>

        {/* Type */}
        <td className="w-10 px-2 py-2">
          <TypeIcon className="w-4 h-4 text-slate-400" />
        </td>

        {/* ID */}
        <td className="w-28 px-2 py-2">
          <code className="text-xs text-slate-500">{task.id}</code>
        </td>

        {/* Title */}
        <td className="px-2 py-2">
          <span className="text-sm text-slate-200">{task.title}</span>
          {task.labels && task.labels.length > 0 && (
            <div className="flex gap-1 mt-1 flex-wrap">
              {task.labels.slice(0, 3).map((label) => (
                <Badge
                  key={label}
                  variant="outline"
                  className="text-xs py-0 h-5"
                >
                  {label}
                </Badge>
              ))}
              {task.labels.length > 3 && (
                <Badge variant="outline" className="text-xs py-0 h-5">
                  +{task.labels.length - 3}
                </Badge>
              )}
            </div>
          )}
        </td>

        {/* Status */}
        <td className="w-28 px-2 py-2">
          <div className={cn('flex items-center gap-1 text-xs', status.color)}>
            <StatusIcon
              className={cn(
                'w-3 h-3',
                task.status === 'running' && 'animate-spin',
              )}
            />
            {status.label}
          </div>
        </td>

        {/* Date */}
        <td className="w-24 px-2 py-2 text-xs text-slate-500">
          {formatDate(task.created_at)}
        </td>
      </tr>

      {/* Expanded Details */}
      {isExpanded && (
        <tr className="bg-slate-800/20">
          <td colSpan={7} className="px-4 py-3">
            <div className="space-y-3">
              {/* Description */}
              {task.description && (
                <div>
                  <h4 className="text-xs font-medium text-slate-400 mb-1">
                    Description
                  </h4>
                  <p className="text-sm text-slate-300 whitespace-pre-wrap max-h-40 overflow-y-auto">
                    {task.description}
                  </p>
                </div>
              )}

              {/* Actions */}
              <div className="flex gap-2 pt-2 border-t border-slate-700">
                {task.status === 'pending' && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={(e) => {
                      e.stopPropagation()
                      onStatusChange('running')
                    }}
                    disabled={isUpdating}
                  >
                    {isUpdating ? (
                      <Loader2 className="w-3 h-3 animate-spin mr-1" />
                    ) : null}
                    Start
                  </Button>
                )}
                {task.status === 'running' && (
                  <>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={(e) => {
                        e.stopPropagation()
                        onStatusChange('paused')
                      }}
                      disabled={isUpdating}
                    >
                      Pause
                    </Button>
                    <Button
                      size="sm"
                      className="bg-green-600 hover:bg-green-700"
                      onClick={(e) => {
                        e.stopPropagation()
                        onStatusChange('completed')
                      }}
                      disabled={isUpdating}
                    >
                      {isUpdating ? (
                        <Loader2 className="w-3 h-3 animate-spin mr-1" />
                      ) : null}
                      Complete
                    </Button>
                  </>
                )}
                {task.status === 'paused' && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={(e) => {
                      e.stopPropagation()
                      onStatusChange('running')
                    }}
                    disabled={isUpdating}
                  >
                    Resume
                  </Button>
                )}
                {task.status === 'completed' && (
                  <span className="text-xs text-green-500">Completed</span>
                )}
                {task.status === 'failed' && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={(e) => {
                      e.stopPropagation()
                      onStatusChange('pending')
                    }}
                    disabled={isUpdating}
                  >
                    Retry
                  </Button>
                )}
              </div>

              {/* Task Log Viewer for running/paused tasks */}
              {(task.status === 'running' || task.status === 'paused') && (
                <div
                  className="pt-3 border-t border-slate-700"
                  onClick={(e) => e.stopPropagation()}
                >
                  <h4 className="text-xs font-medium text-slate-400 mb-2">
                    Task Logs
                  </h4>
                  <TaskLogViewer
                    projectId={projectId}
                    taskId={task.id}
                    className="max-h-[400px]"
                  />
                </div>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  )
}

export function IssueTasksTab({ projectId }: IssueTasksTabProps) {
  const queryClient = useQueryClient()
  const [statusFilter, setStatusFilter] = useState<
    'all' | 'pending' | 'completed'
  >('pending')
  const [typeFilter, setTypeFilter] = useState<TaskType | 'all'>('all')
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [showCreate, setShowCreate] = useState(false)

  // Fetch ready tasks
  const { data: readyData } = useQuery({
    queryKey: ['tasks', projectId, 'ready'],
    queryFn: () => fetchReadyTasks(projectId),
    staleTime: 30000,
  })

  // Fetch filtered tasks
  const {
    data: tasksData,
    isLoading: tasksLoading,
    refetch,
  } = useQuery({
    queryKey: ['tasks', projectId, statusFilter, typeFilter],
    queryFn: () =>
      fetchTasks(projectId, {
        status: statusFilter === 'all' ? undefined : statusFilter,
        type: typeFilter === 'all' ? undefined : typeFilter,
        limit: 200,
      }),
    staleTime: 30000,
  })

  // Status update mutation
  const statusMutation = useMutation({
    mutationFn: ({ taskId, status }: { taskId: string; status: TaskStatus }) =>
      updateTaskStatus(projectId, taskId, status),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tasks', projectId] })
    },
  })

  const handleStatusChange = (taskId: string, status: TaskStatus) => {
    statusMutation.mutate({ taskId, status })
  }

  const readyTasks = readyData?.tasks || []
  const tasks = tasksData?.tasks || []
  const isUpdating = statusMutation.isPending

  // Count stats
  const pendingCount = tasks.filter((t) => t.status === 'pending').length
  const runningCount = tasks.filter((t) => t.status === 'running').length
  const completedCount = tasks.filter((t) => t.status === 'completed').length

  return (
    <div className="space-y-6">
      {/* Stats */}
      <div className="grid grid-cols-4 gap-4">
        <div className="card p-4">
          <div className="text-2xl font-bold text-white">
            {pendingCount + runningCount}
          </div>
          <div className="text-xs text-slate-400">Active</div>
        </div>
        <div className="card p-4">
          <div className="text-2xl font-bold text-yellow-500">
            {runningCount}
          </div>
          <div className="text-xs text-slate-400">Running</div>
        </div>
        <div className="card p-4">
          <div className="text-2xl font-bold text-green-500">
            {completedCount}
          </div>
          <div className="text-xs text-slate-400">Completed</div>
        </div>
        <div className="card p-4">
          <div className="text-2xl font-bold text-slate-400">
            {tasks.length}
          </div>
          <div className="text-xs text-slate-400">Total</div>
        </div>
      </div>

      {/* Ready Work Section */}
      {readyTasks.length > 0 && (
        <div className="card">
          <div className="p-4 border-b border-slate-700">
            <div className="flex items-center gap-2">
              <Zap className="w-5 h-5 text-phosphor-400" />
              <h3 className="font-medium text-white">Ready for Work</h3>
              <Badge variant="outline" className="ml-auto">
                {readyTasks.length}
              </Badge>
            </div>
          </div>
          <div className="divide-y divide-slate-700/50">
            {readyTasks.slice(0, 5).map((task) => {
              const priority =
                priorityConfig[task.priority] || priorityConfig[2]
              const TypeIcon = typeIcons[task.task_type] || ListTodo
              return (
                <div
                  key={task.id}
                  className="p-3 flex items-center gap-3 hover:bg-slate-800/30 cursor-pointer"
                  onClick={() =>
                    setExpandedId(expandedId === task.id ? null : task.id)
                  }
                >
                  <span
                    className={cn(
                      'text-xs font-mono font-bold',
                      priority.color,
                    )}
                  >
                    {priority.label}
                  </span>
                  <TypeIcon className="w-4 h-4 text-slate-400" />
                  <span className="text-sm text-slate-200 flex-1">
                    {task.title}
                  </span>
                  <code className="text-xs text-slate-500">{task.id}</code>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* All Tasks Section */}
      <div className="card">
        <div className="p-4 border-b border-slate-700">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <ListTodo className="w-5 h-5 text-slate-400" />
              <h3 className="font-medium text-white">All Tasks</h3>
            </div>
            <div className="flex items-center gap-2">
              {/* Status Filter */}
              <div className="flex items-center gap-1 bg-slate-800 rounded-lg p-1">
                {(['pending', 'completed', 'all'] as const).map((s) => (
                  <button
                    key={s}
                    onClick={() => setStatusFilter(s)}
                    className={cn(
                      'px-3 py-1 text-xs rounded transition-colors',
                      statusFilter === s
                        ? 'bg-slate-700 text-white'
                        : 'text-slate-400 hover:text-white',
                    )}
                  >
                    {s === 'all' ? 'All' : s === 'pending' ? 'Active' : 'Done'}
                  </button>
                ))}
              </div>

              {/* Type Filter */}
              <select
                value={typeFilter}
                onChange={(e) =>
                  setTypeFilter(e.target.value as TaskType | 'all')
                }
                className="px-2 py-1 text-xs bg-slate-800 border border-slate-700 rounded text-white"
              >
                <option value="all">All Types</option>
                <option value="feature">Features</option>
                <option value="bug">Bugs</option>
                <option value="task">Tasks</option>
              </select>

              {/* Refresh */}
              <Button
                size="sm"
                variant="outline"
                onClick={() => refetch()}
                disabled={tasksLoading}
              >
                <RefreshCw
                  className={cn('w-4 h-4', tasksLoading && 'animate-spin')}
                />
              </Button>

              {/* Create */}
              <Button size="sm" onClick={() => setShowCreate(true)}>
                <Plus className="w-4 h-4 mr-1" />
                New
              </Button>
            </div>
          </div>
        </div>

        {/* Content */}
        {tasksLoading ? (
          <div className="p-8 flex items-center justify-center">
            <Loader2 className="w-6 h-6 animate-spin text-slate-400" />
          </div>
        ) : tasks.length === 0 ? (
          <div className="p-8 text-center text-slate-500">No tasks found</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="text-xs text-slate-500 border-b border-slate-700">
                  <th className="w-8 px-2 py-2"></th>
                  <th className="w-12 px-2 py-2 text-left">Pri</th>
                  <th className="w-10 px-2 py-2"></th>
                  <th className="w-28 px-2 py-2 text-left">ID</th>
                  <th className="px-2 py-2 text-left">Title</th>
                  <th className="w-28 px-2 py-2 text-left">Status</th>
                  <th className="w-24 px-2 py-2 text-left">Created</th>
                </tr>
              </thead>
              <tbody>
                {tasks.map((task) => (
                  <TaskRow
                    key={task.id}
                    task={task}
                    isExpanded={expandedId === task.id}
                    onToggle={() =>
                      setExpandedId(expandedId === task.id ? null : task.id)
                    }
                    onStatusChange={(status) =>
                      handleStatusChange(task.id, status)
                    }
                    isUpdating={isUpdating}
                    projectId={projectId}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Create Task Dialog */}
      <CreateTaskDialog
        open={showCreate}
        onOpenChange={setShowCreate}
        projectId={projectId}
      />
    </div>
  )
}
