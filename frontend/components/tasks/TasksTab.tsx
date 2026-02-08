'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertCircle,
  AlertTriangle,
  ArrowDown,
  ArrowDownCircle,
  ArrowUp,
  Bot,
  Bug,
  CheckCircle2,
  CheckSquare,
  ChevronDown,
  ChevronRight,
  Clock,
  GitPullRequest,
  Loader2,
  OctagonX,
  Package,
  Pause,
  Play,
  Plus,
  RefreshCw,
  Trash2,
  XCircle,
} from 'lucide-react'
import { usePathname, useRouter, useSearchParams } from 'next/navigation'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Button } from '@/components/ui/button'
import {
  fetchBlockedTasks,
  fetchTasks,
  type Task,
  type TaskStatus,
  type TaskType,
} from '@/lib/api'
import type { Subtask } from '@/lib/api/tasks'
import { deleteTask, deleteTasks } from '@/lib/api/tasks'
import { cn } from '@/lib/utils'
import { CriteriaProgress } from './CriteriaProgress'
import { EnrichmentProgress } from './EnrichmentProgress'
import { EnrichmentStatusBadge } from './EnrichmentStatusBadge'
import { SimpleCreateDialog } from './SimpleCreateDialog'
import { SubtaskProgress } from './SubtaskProgress'
import {
  loadFilters,
  saveFilters,
  TaskFilters,
  type TaskFilterValues,
} from './TaskFilters'
import { TaskModal } from './TaskModal'
import { TaskReviewModal } from './TaskReviewModal'

type SortField = 'priority' | 'created_at' | 'title' | 'status' | 'type'
type SortDirection = 'asc' | 'desc'

function formatRelativeTime(dateString: string): string {
  const date = new Date(dateString)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffMins = Math.floor(diffMs / 60000)
  const diffHours = Math.floor(diffMs / 3600000)
  const diffDays = Math.floor(diffMs / 86400000)

  if (diffMins < 1) return 'just now'
  if (diffMins < 60) return `${diffMins}m ago`
  if (diffHours < 24) return `${diffHours}h ago`
  if (diffDays < 7) return `${diffDays}d ago`
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

interface TasksTabProps {
  projectId: string
  initialFilters?: Partial<TaskFilterValues>
}

// Priority config
const priorityConfig: Record<number, { label: string; className: string }> = {
  0: { label: 'P0', className: 'bg-red-500/20 text-red-400 border-red-500/30' },
  1: {
    label: 'P1',
    className: 'bg-rose-500/20 text-rose-400 border-rose-500/30',
  },
  2: {
    label: 'P2',
    className: 'bg-orange-500/20 text-orange-400 border-orange-500/30',
  },
  3: {
    label: 'P3',
    className: 'bg-amber-500/20 text-amber-400 border-amber-500/30',
  },
  4: {
    label: 'P4',
    className: 'bg-slate-500/20 text-slate-400 border-slate-500/30',
  },
}

// Type config
const typeConfig: Record<
  TaskType,
  { icon: React.ReactNode; label: string; className: string }
> = {
  feature: {
    icon: <Package className="h-3.5 w-3.5" />,
    label: 'Feature',
    className: 'text-purple-400',
  },
  bug: {
    icon: <Bug className="h-3.5 w-3.5" />,
    label: 'Bug',
    className: 'text-rose-400',
  },
  task: {
    icon: <CheckSquare className="h-3.5 w-3.5" />,
    label: 'Task',
    className: 'text-blue-400',
  },
  refactor: {
    icon: <RefreshCw className="h-3.5 w-3.5" />,
    label: 'Refactor',
    className: 'text-cyan-400',
  },
  debt: {
    icon: <AlertTriangle className="h-3.5 w-3.5" />,
    label: 'Tech Debt',
    className: 'text-amber-400',
  },
  regression: {
    icon: <ArrowDownCircle className="h-3.5 w-3.5" />,
    label: 'Regression',
    className: 'text-orange-400',
  },
}

// Status config
const statusConfig: Record<
  TaskStatus,
  { icon: React.ReactNode; className: string }
> = {
  pending: {
    icon: <Clock className="h-3.5 w-3.5" />,
    className: 'text-slate-400',
  },
  queue: {
    icon: <Clock className="h-3.5 w-3.5" />,
    className: 'text-sky-400',
  },
  running: {
    icon: <Play className="h-3.5 w-3.5" />,
    className: 'text-blue-400',
  },
  paused: {
    icon: <Pause className="h-3.5 w-3.5" />,
    className: 'text-amber-400',
  },
  blocked: {
    icon: <OctagonX className="h-3.5 w-3.5" />,
    className: 'text-orange-400',
  },
  pr_created: {
    icon: <GitPullRequest className="h-3.5 w-3.5" />,
    className: 'text-amber-400',
  },
  ai_reviewing: {
    icon: <Bot className="h-3.5 w-3.5" />,
    className: 'text-amber-400',
  },
  completed: {
    icon: <CheckCircle2 className="h-3.5 w-3.5" />,
    className: 'text-green-400',
  },
  failed: {
    icon: <XCircle className="h-3.5 w-3.5" />,
    className: 'text-rose-400',
  },
  cancelled: {
    icon: <XCircle className="h-3.5 w-3.5" />,
    className: 'text-slate-500',
  },
}

function TaskRow({
  task,
  isExpanded,
  onToggle,
  onDelete,
  isSelected,
  onToggleSelect,
  subtasks,
}: {
  task: Task
  isExpanded: boolean
  onToggle: () => void
  onDelete?: (taskId: string) => void
  isSelected?: boolean
  onToggleSelect?: (taskId: string) => void
  onTaskUpdated?: (task: Task) => void
  onTaskDeleted?: () => void
  subtasks: Subtask[]
  projectId: string
}) {
  const priority = task.priority ?? 2
  const taskType = task.task_type ?? 'task'
  const priorityStyle = priorityConfig[priority] || priorityConfig[2]
  const typeStyle = typeConfig[taskType] || typeConfig.task
  const statusStyle = statusConfig[task.status] || statusConfig.pending

  // Phase badge config - maps status to kanban column names (DRY with TaskKanbanBoard)
  const statusToKanbanLabel: Record<
    string,
    { label: string; className: string }
  > = {
    pending: { label: 'Planning', className: 'bg-slate-600/50 text-slate-300' },
    running: {
      label: 'In Progress',
      className: 'bg-blue-600/50 text-blue-300',
    },
    paused: {
      label: 'In Progress',
      className: 'bg-amber-600/50 text-amber-300',
    },
    blocked: {
      label: 'In Progress',
      className: 'bg-orange-600/50 text-orange-300',
    },
    ai_reviewing: {
      label: 'AI Review',
      className: 'bg-cyan-600/50 text-cyan-300',
    },
    pr_created: {
      label: 'AI Review',
      className: 'bg-purple-600/50 text-purple-300',
    },
    completed: { label: 'Done', className: 'bg-green-600/50 text-green-300' },
    failed: { label: 'Done', className: 'bg-red-600/50 text-red-300' },
    cancelled: { label: 'Done', className: 'bg-slate-600/50 text-slate-300' },
  }
  const phaseStyle =
    statusToKanbanLabel[task.status] || statusToKanbanLabel.pending

  return (
    <>
      <tr
        className={cn(
          'border-b border-slate-800 hover:bg-slate-800/30 transition-colors',
          isExpanded && 'bg-slate-800/50',
          isSelected && 'bg-blue-500/10',
        )}
      >
        {/* Checkbox */}
        {onToggleSelect && (
          <td className="w-8 px-2 py-3" onClick={(e) => e.stopPropagation()}>
            <input
              type="checkbox"
              checked={isSelected}
              onChange={() => onToggleSelect(task.id)}
              className="w-4 h-4 rounded border-slate-600 bg-slate-700 text-phosphor-500 focus:ring-phosphor-500 focus:ring-offset-0 cursor-pointer"
            />
          </td>
        )}

        {/* Expand */}
        <td className="w-8 px-2 py-3 cursor-pointer" onClick={onToggle}>
          {isExpanded ? (
            <ChevronDown className="w-4 h-4 text-slate-500" />
          ) : (
            <ChevronRight className="w-4 h-4 text-slate-500" />
          )}
        </td>

        {/* Priority */}
        <td className="px-3 py-3 cursor-pointer" onClick={onToggle}>
          <span
            className={`text-xs px-1.5 py-0.5 rounded border mono font-medium ${priorityStyle.className}`}
          >
            {priorityStyle.label}
          </span>
        </td>

        {/* Type */}
        <td className="px-3 py-3 cursor-pointer" onClick={onToggle}>
          <span className={`flex items-center gap-1.5 ${typeStyle.className}`}>
            {typeStyle.icon}
            <span className="text-xs">{typeStyle.label}</span>
          </span>
        </td>

        {/* ID */}
        <td className="px-3 py-3 cursor-pointer" onClick={onToggle}>
          <span className="text-xs mono text-slate-500">{task.id}</span>
        </td>

        {/* Title + Warning */}
        <td className="px-3 py-3 cursor-pointer" onClick={onToggle}>
          <div className="flex items-center gap-2">
            <span className="text-sm text-slate-200 line-clamp-1">
              {task.title}
            </span>
            {!task.objective && task.enrichment_status !== 'enriching' && (
              <span title="No objective set">
                <AlertCircle className="w-3.5 h-3.5 text-amber-500 flex-shrink-0" />
              </span>
            )}
          </div>
        </td>

        {/* Phase Badge */}
        <td className="px-3 py-3 cursor-pointer" onClick={onToggle}>
          <span
            className={`text-2xs px-1.5 py-0.5 rounded font-medium ${phaseStyle.className}`}
          >
            {phaseStyle.label}
          </span>
        </td>

        {/* Progress Indicators */}
        <td className="px-3 py-3 cursor-pointer" onClick={onToggle}>
          <div className="flex items-center gap-3">
            {/* Criteria Progress */}
            {task.acceptance_criteria &&
              task.acceptance_criteria.length > 0 && (
                <CriteriaProgress
                  criteria={task.acceptance_criteria}
                  maxVisible={4}
                />
              )}
            {/* Subtask Progress */}
            {subtasks.length > 0 && (
              <SubtaskProgress subtasks={subtasks} maxVisible={5} />
            )}
            {/* Enrichment Status Badge for non-accepted tasks */}
            <EnrichmentStatusBadge status={task.enrichment_status} />
          </div>
        </td>

        {/* Status */}
        <td className="px-3 py-3 cursor-pointer" onClick={onToggle}>
          <span
            className={`flex items-center gap-1.5 ${statusStyle.className}`}
          >
            {statusStyle.icon}
            <span className="text-xs capitalize">{task.status}</span>
          </span>
        </td>

        {/* Created */}
        <td className="px-3 py-3 cursor-pointer" onClick={onToggle}>
          <span className="text-xs text-slate-500">
            {task.created_at ? formatRelativeTime(task.created_at) : '-'}
          </span>
        </td>

        {/* Actions */}
        {onDelete && (
          <td className="px-3 py-3" onClick={(e) => e.stopPropagation()}>
            <button
              onClick={() => onDelete(task.id)}
              className="p-1 rounded hover:bg-red-500/20 text-slate-500 hover:text-red-400 transition-colors"
              title="Delete task"
            >
              <Trash2 className="w-4 h-4" />
            </button>
          </td>
        )}
      </tr>

      {/* Expanded inline view removed - now using TaskModal */}
    </>
  )
}

export function TasksTab({ projectId, initialFilters }: TasksTabProps) {
  const queryClient = useQueryClient()
  const router = useRouter()
  const pathname = usePathname()
  const [filters, setFilters] = useState<TaskFilterValues>(() => {
    const loaded = loadFilters()
    return { ...loaded, ...initialFilters }
  })
  const searchParams = useSearchParams()
  const urlTaskId = searchParams.get('task')
  const urlModal = searchParams.get('modal')

  const [sortField, setSortField] = useState<SortField>('created_at')
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc')
  const [modalTaskId, setModalTaskId] = useState<string | null>(urlTaskId)
  const [modalOpen, setModalOpen] = useState(!!urlTaskId)
  const [selectedTask, setSelectedTask] = useState<Task | null>(null)
  const [showCreate, setShowCreate] = useState(urlModal === 'create-task')
  const [selectedTaskIds, setSelectedTaskIds] = useState<Set<string>>(new Set())
  const [deleteConfirmTask, setDeleteConfirmTask] = useState<Task | null>(null)
  const [bulkDeleteConfirm, setBulkDeleteConfirm] = useState(false)

  // Helper to update URL params
  const updateUrlParams = useCallback(
    (params: Record<string, string | null>) => {
      const newParams = new URLSearchParams(searchParams.toString())
      Object.entries(params).forEach(([key, value]) => {
        if (value === null) {
          newParams.delete(key)
        } else {
          newParams.set(key, value)
        }
      })
      const query = newParams.toString()
      router.replace(`${pathname}${query ? `?${query}` : ''}`, {
        scroll: false,
      })
    },
    [router, pathname, searchParams],
  )

  // Handle URL task param changes
  useEffect(() => {
    if (urlTaskId) {
      setModalTaskId(urlTaskId)
      setModalOpen(true)
    }
  }, [urlTaskId])

  // Handle URL modal param changes
  useEffect(() => {
    if (urlModal === 'create-task') {
      setShowCreate(true)
    }
    // Note: task-review requires a task object, so it's typically opened
    // via the enrichment flow rather than direct URL access
  }, [urlModal])

  // Enrichment flow state
  const [enrichingTask, setEnrichingTask] = useState<Task | null>(null)
  const [reviewingTask, setReviewingTask] = useState<Task | null>(null)

  // Persist filters when they change
  useEffect(() => {
    saveFilters(filters)
  }, [filters])

  // Handle column header click for sorting
  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDirection((prev) => (prev === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortField(field)
      setSortDirection(field === 'created_at' ? 'desc' : 'asc')
    }
  }

  // Render sort indicator
  const SortIndicator = ({ field }: { field: SortField }) => {
    if (sortField !== field) return null
    return sortDirection === 'asc' ? (
      <ArrowUp className="w-3 h-3 inline ml-1" />
    ) : (
      <ArrowDown className="w-3 h-3 inline ml-1" />
    )
  }

  // Fetch all tasks
  const {
    data: tasksData,
    isLoading: tasksLoading,
    isFetching: tasksFetching,
    refetch: refetchTasks,
  } = useQuery({
    queryKey: ['tasks', projectId, 'all'],
    queryFn: () => fetchTasks(projectId, { limit: 500 }),
    staleTime: 30000,
  })

  // Fetch blocked tasks (separate query since it's a different endpoint)
  const {
    data: blockedTasksData,
    isLoading: blockedLoading,
    isFetching: blockedFetching,
    refetch: refetchBlocked,
  } = useQuery({
    queryKey: ['tasks', projectId, 'blocked'],
    queryFn: () => fetchBlockedTasks(projectId, 500),
    staleTime: 30000,
    enabled: filters.status === 'blocked', // Only fetch when filter is blocked
  })

  // Unified refetch function
  const refetch = useCallback(() => {
    refetchTasks()
    if (filters.status === 'blocked') {
      refetchBlocked()
    }
  }, [refetchTasks, refetchBlocked, filters.status])

  // Handler for task created from SimpleCreateDialog
  const handleTaskCreated = useCallback(
    (task: Task, mode: 'queue' | 'verify') => {
      if (mode === 'verify' && task.enrichment_status === 'review') {
        // Sync mode completed - go directly to review
        setReviewingTask(task)
      } else if (mode === 'queue' && task.enrichment_status === 'enriching') {
        // Async mode - show enrichment progress
        setEnrichingTask(task)
      }
      // Refresh task list
      refetch()
    },
    [refetch],
  )

  // Handler for task updated
  const handleTaskUpdated = useCallback(
    (updatedTask: Task) => {
      queryClient.setQueryData(
        ['tasks', projectId, 'all'],
        (old: { tasks: Task[] } | undefined) => {
          if (!old) return old
          return {
            ...old,
            tasks: old.tasks.map((t) =>
              t.id === updatedTask.id ? updatedTask : t,
            ),
          }
        },
      )
    },
    [queryClient, projectId],
  )

  // Handler for enrichment complete
  const handleEnrichmentComplete = useCallback(
    (task: Task) => {
      setEnrichingTask(null)
      if (task.enrichment_status === 'review') {
        setReviewingTask(task)
      }
      refetch()
    },
    [refetch],
  )

  // Handler for task accepted from review modal
  const handleTaskAccepted = useCallback(
    (acceptedTask: Task) => {
      setReviewingTask(null)
      // Update task in cache
      handleTaskUpdated(acceptedTask)
      refetch()
    },
    [refetch, handleTaskUpdated],
  )

  // Handler for task deleted
  const handleTaskDeleted = useCallback(() => {
    setModalOpen(false)
    setModalTaskId(null)
    refetch()
  }, [refetch])

  // Delete mutations
  const deleteMutation = useMutation({
    mutationFn: (taskId: string) => deleteTask(projectId, taskId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tasks', projectId] })
      setDeleteConfirmTask(null)
      setSelectedTaskIds(new Set())
    },
  })

  const bulkDeleteMutation = useMutation({
    mutationFn: (taskIds: string[]) => deleteTasks(projectId, taskIds),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tasks', projectId] })
      setBulkDeleteConfirm(false)
      setSelectedTaskIds(new Set())
    },
  })

  // Delete handlers
  const handleDeleteClick = (taskId: string) => {
    const task = filteredTasks.find((t) => t.id === taskId)
    if (task) {
      setDeleteConfirmTask(task)
    }
  }

  const handleDeleteConfirm = () => {
    if (deleteConfirmTask) {
      deleteMutation.mutate(deleteConfirmTask.id)
    }
  }

  const handleBulkDelete = () => {
    if (selectedTaskIds.size > 0) {
      bulkDeleteMutation.mutate(Array.from(selectedTaskIds))
    }
  }

  const handleToggleSelect = (taskId: string) => {
    setSelectedTaskIds((prev) => {
      const next = new Set(prev)
      if (next.has(taskId)) {
        next.delete(taskId)
      } else {
        next.add(taskId)
      }
      return next
    })
  }

  const handleToggleSelectAll = () => {
    if (selectedTaskIds.size === filteredTasks.length) {
      setSelectedTaskIds(new Set())
    } else {
      setSelectedTaskIds(new Set(filteredTasks.map((t) => t.id)))
    }
  }

  // Apply client-side filters and sorting
  const filteredTasks = useMemo(() => {
    // For "blocked" status, use the blocked tasks endpoint data
    const tasks =
      filters.status === 'blocked'
        ? blockedTasksData?.tasks || []
        : tasksData?.tasks || []

    const filtered = tasks.filter((task) => {
      // Type filter
      if (filters.type !== 'all' && task.task_type !== filters.type) {
        return false
      }

      // Status filter (skip for "blocked" since we already fetched blocked tasks)
      if (filters.status !== 'all' && filters.status !== 'blocked') {
        if (filters.status === 'active') {
          if (
            task.status === 'completed' ||
            task.status === 'failed' ||
            task.status === 'cancelled'
          ) {
            return false
          }
        } else if (task.status !== filters.status) {
          return false
        }
      }

      // Priority filter
      if (filters.priority !== 'all' && task.priority !== filters.priority) {
        return false
      }

      return true
    })

    // Sort tasks
    return filtered.sort((a, b) => {
      let comparison = 0
      switch (sortField) {
        case 'priority':
          comparison = (a.priority ?? 2) - (b.priority ?? 2)
          break
        case 'created_at':
          comparison =
            new Date(a.created_at || 0).getTime() -
            new Date(b.created_at || 0).getTime()
          break
        case 'title':
          comparison = a.title.localeCompare(b.title)
          break
        case 'status':
          comparison = a.status.localeCompare(b.status)
          break
        case 'type':
          comparison = (a.task_type || 'task').localeCompare(
            b.task_type || 'task',
          )
          break
      }
      return sortDirection === 'asc' ? comparison : -comparison
    })
  }, [tasksData, blockedTasksData, filters, sortField, sortDirection])

  const isLoading = filters.status === 'blocked' ? blockedLoading : tasksLoading
  const isFetching =
    filters.status === 'blocked' ? blockedFetching : tasksFetching

  return (
    <div className="space-y-4">
      {/* Header with filters */}
      <div className="flex items-center justify-between">
        <TaskFilters
          projectId={projectId}
          filters={filters}
          onChange={setFilters}
        />
        <div className="flex items-center gap-2">
          {selectedTaskIds.size > 0 && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => setBulkDeleteConfirm(true)}
              className="border-red-600 text-red-400 hover:bg-red-500/20"
            >
              <Trash2 className="w-4 h-4 mr-1" />
              Delete {selectedTaskIds.size} task
              {selectedTaskIds.size !== 1 ? 's' : ''}
            </Button>
          )}
          <Button
            size="sm"
            variant="outline"
            onClick={() => refetch()}
            disabled={isFetching}
          >
            <RefreshCw
              className={cn('w-4 h-4', isFetching && 'animate-spin')}
            />
          </Button>
          <Button
            size="sm"
            onClick={() => {
              setShowCreate(true)
              updateUrlParams({ modal: 'create-task' })
            }}
            data-testid="new-task-button"
          >
            <Plus className="w-4 h-4 mr-1" />
            New Task
          </Button>
        </div>
      </div>

      {/* Tasks Table */}
      <div className="rounded-lg border border-slate-700 bg-slate-900/50 overflow-hidden">
        {isLoading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="h-6 w-6 animate-spin text-slate-500" />
          </div>
        ) : filteredTasks.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-slate-500">
            <CheckCircle2 className="h-8 w-8 mb-2" />
            <span className="text-sm">No tasks found</span>
            <span className="text-xs text-slate-600">
              Try adjusting your filters
            </span>
          </div>
        ) : (
          <table className="w-full">
            <thead>
              <tr className="border-b border-slate-700 bg-slate-800/50">
                <th className="w-8 px-2 py-2">
                  <input
                    type="checkbox"
                    checked={
                      filteredTasks.length > 0 &&
                      selectedTaskIds.size === filteredTasks.length
                    }
                    onChange={handleToggleSelectAll}
                    className="w-4 h-4 rounded border-slate-600 bg-slate-700 text-phosphor-500 focus:ring-phosphor-500 focus:ring-offset-0 cursor-pointer"
                  />
                </th>
                <th className="w-8 px-2 py-2"></th>
                <th
                  className="px-3 py-2 text-left text-xs font-medium text-slate-400 w-16 cursor-pointer hover:text-slate-200 select-none"
                  onClick={() => handleSort('priority')}
                >
                  Pri
                  <SortIndicator field="priority" />
                </th>
                <th
                  className="px-3 py-2 text-left text-xs font-medium text-slate-400 w-20 cursor-pointer hover:text-slate-200 select-none"
                  onClick={() => handleSort('type')}
                >
                  Type
                  <SortIndicator field="type" />
                </th>
                <th className="px-3 py-2 text-left text-xs font-medium text-slate-400 w-28">
                  ID
                </th>
                <th
                  className="px-3 py-2 text-left text-xs font-medium text-slate-400 cursor-pointer hover:text-slate-200 select-none"
                  onClick={() => handleSort('title')}
                >
                  Title
                  <SortIndicator field="title" />
                </th>
                <th className="px-3 py-2 text-left text-xs font-medium text-slate-400 w-16">
                  Phase
                </th>
                <th className="px-3 py-2 text-left text-xs font-medium text-slate-400 w-36">
                  Progress
                </th>
                <th
                  className="px-3 py-2 text-left text-xs font-medium text-slate-400 w-24 cursor-pointer hover:text-slate-200 select-none"
                  onClick={() => handleSort('status')}
                >
                  Status
                  <SortIndicator field="status" />
                </th>
                <th
                  className="px-3 py-2 text-left text-xs font-medium text-slate-400 w-24 cursor-pointer hover:text-slate-200 select-none"
                  onClick={() => handleSort('created_at')}
                >
                  Created
                  <SortIndicator field="created_at" />
                </th>
                <th className="px-3 py-2 text-left text-xs font-medium text-slate-400 w-16">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody>
              {filteredTasks.map((task) => (
                <TaskRow
                  key={task.id}
                  task={task}
                  isExpanded={false}
                  onToggle={() => {
                    setModalTaskId(task.id)
                    setSelectedTask(task)
                    setModalOpen(true)
                    updateUrlParams({ task: task.id })
                  }}
                  onDelete={handleDeleteClick}
                  isSelected={selectedTaskIds.has(task.id)}
                  onToggleSelect={handleToggleSelect}
                  onTaskUpdated={handleTaskUpdated}
                  onTaskDeleted={handleTaskDeleted}
                  subtasks={[]}
                  projectId={projectId}
                />
              ))}
            </tbody>
          </table>
        )}

        {/* Footer with count */}
        <div className="px-4 py-2 border-t border-slate-700 bg-slate-800/30">
          <span className="text-xs text-slate-500">
            {filteredTasks.length} task{filteredTasks.length !== 1 ? 's' : ''}
          </span>
        </div>
      </div>

      {/* Task Detail Modal */}
      <TaskModal
        taskId={modalTaskId}
        projectId={projectId}
        open={modalOpen}
        onOpenChange={(open) => {
          setModalOpen(open)
          if (!open) {
            updateUrlParams({ task: null })
          }
        }}
        onTaskUpdate={(task) => {
          setSelectedTask(task)
          handleTaskUpdated(task)
        }}
        initialTask={selectedTask}
      />

      {/* Simple Create Task Dialog */}
      <SimpleCreateDialog
        open={showCreate}
        onOpenChange={(open) => {
          setShowCreate(open)
          updateUrlParams({ modal: open ? 'create-task' : null })
        }}
        projectId={projectId}
        onTaskCreated={handleTaskCreated}
      />

      {/* Enrichment Progress Modal - shown inline when enriching */}
      {enrichingTask && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="bg-slate-900 border border-slate-700 rounded-lg p-6 max-w-md w-full mx-4 shadow-2xl">
            <EnrichmentProgress
              projectId={projectId}
              task={enrichingTask}
              onComplete={handleEnrichmentComplete}
              onError={(err) => {
                console.error('Enrichment error:', err)
                setEnrichingTask(null)
              }}
            />
            <div className="mt-4 pt-4 border-t border-slate-800 flex justify-end">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setEnrichingTask(null)}
                className="text-slate-500 hover:text-slate-300"
              >
                Run in Background
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Task Review Modal */}
      {reviewingTask && (
        <TaskReviewModal
          open={!!reviewingTask}
          onOpenChange={(open) => {
            if (!open) setReviewingTask(null)
          }}
          projectId={projectId}
          task={reviewingTask}
          onAccept={handleTaskAccepted}
          onDiscard={() => setReviewingTask(null)}
        />
      )}

      {/* Single Delete Confirmation Dialog */}
      {deleteConfirmTask && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
          onClick={() => setDeleteConfirmTask(null)}
        >
          <div
            className="bg-slate-800 rounded-lg border border-slate-700 p-6 w-full max-w-md mx-4 shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start gap-3 mb-4">
              <AlertCircle className="w-6 h-6 text-red-400 shrink-0 mt-0.5" />
              <div>
                <h3 className="text-lg font-semibold text-slate-100 mb-2">
                  Delete Task
                </h3>
                <p className="text-sm text-slate-300 mb-2">
                  Are you sure you want to delete this task?
                </p>
                <div className="text-sm font-mono text-slate-400 bg-slate-900 px-3 py-2 rounded mb-3">
                  {deleteConfirmTask.id}: {deleteConfirmTask.title}
                </div>
                <p className="text-sm text-red-400">
                  This will permanently delete the task and all its subtasks,
                  criteria, and dependencies. This cannot be undone.
                </p>
              </div>
            </div>

            <div className="flex items-center justify-end gap-3">
              <button
                onClick={() => setDeleteConfirmTask(null)}
                disabled={deleteMutation.isPending}
                className="px-4 py-2 text-sm text-slate-400 hover:text-slate-200 transition-colors disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={handleDeleteConfirm}
                disabled={deleteMutation.isPending}
                className="flex items-center gap-2 px-4 py-2 text-sm bg-red-600 text-white hover:bg-red-500 rounded-md transition-colors font-medium disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {deleteMutation.isPending ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Deleting...
                  </>
                ) : (
                  'Delete'
                )}
              </button>
            </div>

            {deleteMutation.isError && (
              <p className="mt-3 text-sm text-red-400">
                Failed to delete task. Please try again.
              </p>
            )}
          </div>
        </div>
      )}

      {/* Bulk Delete Confirmation Dialog */}
      {bulkDeleteConfirm && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
          onClick={() => setBulkDeleteConfirm(false)}
        >
          <div
            className="bg-slate-800 rounded-lg border border-slate-700 p-6 w-full max-w-md mx-4 shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start gap-3 mb-4">
              <AlertCircle className="w-6 h-6 text-red-400 shrink-0 mt-0.5" />
              <div>
                <h3 className="text-lg font-semibold text-slate-100 mb-2">
                  Delete {selectedTaskIds.size} Task
                  {selectedTaskIds.size !== 1 ? 's' : ''}
                </h3>
                <p className="text-sm text-slate-300 mb-3">
                  Are you sure you want to delete these tasks?
                </p>
                <div className="text-sm font-mono text-slate-400 bg-slate-900 px-3 py-2 rounded mb-3 max-h-32 overflow-y-auto">
                  {Array.from(selectedTaskIds)
                    .slice(0, 5)
                    .map((id) => (
                      <div key={id}>{id}</div>
                    ))}
                  {selectedTaskIds.size > 5 && (
                    <div className="text-slate-500 italic">
                      ...and {selectedTaskIds.size - 5} more
                    </div>
                  )}
                </div>
                <p className="text-sm text-red-400">
                  This will permanently delete all selected tasks and their
                  subtasks, criteria, and dependencies. This cannot be undone.
                </p>
              </div>
            </div>

            <div className="flex items-center justify-end gap-3">
              <button
                onClick={() => setBulkDeleteConfirm(false)}
                disabled={bulkDeleteMutation.isPending}
                className="px-4 py-2 text-sm text-slate-400 hover:text-slate-200 transition-colors disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={handleBulkDelete}
                disabled={bulkDeleteMutation.isPending}
                className="flex items-center gap-2 px-4 py-2 text-sm bg-red-600 text-white hover:bg-red-500 rounded-md transition-colors font-medium disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {bulkDeleteMutation.isPending ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Deleting...
                  </>
                ) : (
                  `Delete ${selectedTaskIds.size}`
                )}
              </button>
            </div>

            {bulkDeleteMutation.isError && (
              <p className="mt-3 text-sm text-red-400">
                Failed to delete tasks. Please try again.
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
