'use client'

import { useQuery } from '@tanstack/react-query'
import { AlertCircle } from 'lucide-react'
import Link from 'next/link'
import { useParams, usePathname, useRouter, useSearchParams } from 'next/navigation'
import { useCallback, useEffect, useState } from 'react'
import { toast } from 'sonner'
import { BlockedTasksAlert } from '@/components/dashboard'
import { EscalationPanel } from '@/components/execution/EscalationPanel'
import { ExplorerTab } from '@/components/explorer/ExplorerTab'
import type { ExplorerType } from '@/components/explorer/types'
import { HealthTab } from '@/components/health/HealthTab'
import { TaskKanbanBoard } from '@/components/kanban/TaskKanbanBoard'
import { TaskIdeationDialog } from '@/components/tasks/TaskIdeationDialog'
import type { TaskFilterValues } from '@/components/tasks/TaskFilters'
import { TaskModal } from '@/components/tasks/TaskModal'
import { TasksTab } from '@/components/tasks/TasksTab'
import { TasksViewToolbar } from '@/components/tasks/TasksViewToolbar'
import { useViewMode } from '@/components/tasks/hooks/useViewMode'
import {
  fetchProject,
  fetchTasks,
  type Task,
  type TaskStatus,
  updateTaskStatus,
} from '@/lib/api'
import { executeTask } from '@/lib/api/tasks'
import { type TabId, useTabPersistence } from '@/lib/hooks/useTabPersistence'
import { buildUrlWithUpdatedSearchParams } from '@/lib/search-params'
import { taskQueryKeys } from '@/lib/task-cache'
import { useTaskMutationSync } from '@/lib/task-mutation-sync'
import { STALE_GIT } from '@/lib/polling'
import { getErrorMessage } from '@/lib/utils'

export function ProjectDetailClient() {
  const params = useParams()
  const searchParams = useSearchParams()
  const pathname = usePathname()
  const router = useRouter()
  const projectId = params.id as string
  const { invalidateTasks, syncUpdatedTask } = useTaskMutationSync(projectId)

  // Tab persistence hook (handles localStorage and URL sync)
  const urlTab = searchParams.get('tab') as TabId | null
  const urlExplorerType = searchParams.get('type') as ExplorerType | null
  const { activeTab, explorerType, setExplorerType } = useTabPersistence({
    projectId,
    urlTab,
    urlExplorerType,
  })

  // Get task filter params from URL
  const urlTaskStatus = searchParams.get('status')
  const urlTaskType = searchParams.get('taskType')
  const taskInitialFilters: Partial<TaskFilterValues> = {}
  if (
    urlTaskStatus &&
    [
      'all',
      'active',
      'blocked',
      'conflicted',
      'pending',
      'running',
      'completed',
      'failed',
    ].includes(urlTaskStatus)
  ) {
    taskInitialFilters.status = urlTaskStatus as TaskFilterValues['status']
  }
  if (urlTaskType && ['all', 'feature', 'bug', 'task'].includes(urlTaskType)) {
    taskInitialFilters.type = urlTaskType as TaskFilterValues['type']
  }

  const updateUrlParams = useCallback(
    (params: Record<string, string | null>) => {
      router.replace(
        buildUrlWithUpdatedSearchParams(pathname, searchParams, params),
        { scroll: false },
      )
    },
    [pathname, router, searchParams],
  )

  // Update URL when explorer type changes (without full navigation)
  const handleExplorerTypeChange = (type: ExplorerType) => {
    setExplorerType(type)
    updateUrlParams({ tab: 'explorer', type })
  }

  // Auto-open task from URL query param
  const urlTaskId = searchParams.get('task')
  const urlModal = searchParams.get('modal')

  // View mode (board | table) for unified tasks tab
  const { viewMode, setViewMode } = useViewMode(projectId)

  // Kanban state
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(urlTaskId)
  const [selectedTask, setSelectedTask] = useState<Task | null>(null)
  const [modalOpen, setModalOpen] = useState(!!urlTaskId)
  const [createTaskDialogOpen, setCreateTaskDialogOpen] = useState(false)
  const [escalationOpen, setEscalationOpen] = useState(false)
  const [escalationTask, _setEscalationTask] = useState<Task | null>(null)

  // Handle URL task param changes
  useEffect(() => {
    if (urlTaskId) {
      setSelectedTaskId(urlTaskId)
      setModalOpen(true)
      return
    }
    setSelectedTaskId(null)
    setSelectedTask(null)
    setModalOpen(false)
  }, [urlTaskId])

  useEffect(() => {
    setCreateTaskDialogOpen(viewMode === 'board' && urlModal === 'create-task')
  }, [urlModal, viewMode])

  const {
    data: project,
    isLoading,
    error,
  } = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => fetchProject(projectId),
  })

  // Tasks for Kanban (fetch with feature context)
  const { data: kanbanTasksData } = useQuery({
    queryKey: taskQueryKeys.kanban(projectId),
    queryFn: () => fetchTasks(projectId, { include: 'feature', limit: 500 }),
    staleTime: STALE_GIT,
    enabled: activeTab === 'tasks' && viewMode === 'board',
  })
  const kanbanTasks = kanbanTasksData?.tasks ?? []

  // Kanban handlers
  const handleTaskStatusChange = async (
    taskId: string,
    newStatus: TaskStatus,
  ) => {
    try {
      const updated = await updateTaskStatus(projectId, taskId, newStatus)
      syncUpdatedTask(updated)
    } catch (err) {
      toast.error(getErrorMessage(err, 'Failed to update task status'))
    }
  }

  const handleTaskClick = (task: Task) => {
    setSelectedTaskId(task.id)
    setSelectedTask(task)
    setModalOpen(true)
    updateUrlParams({ task: task.id })
  }

  const handleApproveAndResume = async (_message?: string) => {
    if (!escalationTask) return
    try {
      await executeTask(projectId, escalationTask.id)
      invalidateTasks()
      setEscalationOpen(false)
      toast.success('Task resumed')
    } catch (err) {
      toast.error(getErrorMessage(err, 'Failed to resume task'))
    }
  }

  const handleTaskUpdate = (task: Task) => {
    setSelectedTask(task)
    syncUpdatedTask(task)
  }

  const handleNewTask = () => {
    setCreateTaskDialogOpen(true)
    updateUrlParams({ modal: 'create-task' })
  }

  const handleCreateDialogChange = (open: boolean) => {
    setCreateTaskDialogOpen(open)
    updateUrlParams({ modal: open ? 'create-task' : null })
  }

  const handleTaskModalOpenChange = (open: boolean) => {
    setModalOpen(open)
    if (!open) {
      updateUrlParams({ task: null })
    }
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="w-8 h-8 border-2 border-outrun-500/30 border-t-outrun-500 rounded-full animate-spin" />
      </div>
    )
  }

  if (error || !project) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="card p-8 text-center max-w-md">
          <AlertCircle className="w-10 h-10 text-rose-500 mx-auto mb-4" />
          <h2 className="display text-lg font-semibold text-slate-100 mb-2">
            Project Not Found
          </h2>
          <p className="text-slate-400 mb-6">
            The project you&apos;re looking for doesn&apos;t exist or
            couldn&apos;t be loaded.
          </p>
          <Link href="/" className="btn-primary inline-flex items-center gap-2">
            Back to Dashboard
          </Link>
        </div>
      </div>
    )
  }

  return (
    <div className="h-full flex flex-col">
      {/* Tab Content - Full height, no header redundancy */}
      <section className="flex-1 overflow-hidden">
        {activeTab === 'tasks' && (
          <div className="h-full overflow-auto p-4 space-y-4">
            <TasksViewToolbar
              viewMode={viewMode}
              onViewModeChange={setViewMode}
              onNewTask={handleNewTask}
            />
            {viewMode === 'board' ? (
              <>
                <BlockedTasksAlert projectId={projectId} onTaskClick={(taskId) => {
                  setSelectedTaskId(taskId)
                  setModalOpen(true)
                  updateUrlParams({ task: taskId })
                }} />
                <TaskKanbanBoard
                  tasks={kanbanTasks}
                  projectId={projectId}
                  onStatusChange={handleTaskStatusChange}
                  onTaskClick={handleTaskClick}
                  onNewTask={handleNewTask}
                />
                <TaskModal
                  taskId={selectedTaskId}
                  projectId={projectId}
                  open={modalOpen}
                  onOpenChange={handleTaskModalOpenChange}
                  onTaskUpdate={handleTaskUpdate}
                  initialTask={selectedTask}
                />
                {escalationTask && (
                  <EscalationPanel
                    task={escalationTask}
                    isOpen={escalationOpen}
                    onClose={() => setEscalationOpen(false)}
                    onApproveAndResume={handleApproveAndResume}
                  />
                )}
              </>
            ) : (
              <TasksTab
                projectId={projectId}
                initialFilters={taskInitialFilters}
              />
            )}
            <TaskIdeationDialog
              open={createTaskDialogOpen}
              onOpenChange={handleCreateDialogChange}
              projectId={projectId}
            />
          </div>
        )}
        {activeTab === 'explorer' && (
          <div className="h-full overflow-auto p-4">
            <ExplorerTab
              projectId={projectId}
              initialType={explorerType}
              onTypeChange={handleExplorerTypeChange}
            />
          </div>
        )}
        {activeTab === 'health' && (
          <div className="h-full overflow-auto p-4">
            <HealthTab projectId={projectId} />
          </div>
        )}
      </section>
    </div>
  )
}
