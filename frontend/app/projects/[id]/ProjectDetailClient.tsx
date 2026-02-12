'use client'

import { useQuery } from '@tanstack/react-query'
import { AlertCircle } from 'lucide-react'
import Link from 'next/link'
import { useParams, useRouter, useSearchParams } from 'next/navigation'
import { useEffect, useState } from 'react'
import { BlockedTasksAlert } from '@/components/dashboard'
import { EscalationPanel } from '@/components/execution/EscalationPanel'
import { ExplorerTab } from '@/components/explorer/ExplorerTab'
import type { ExplorerType } from '@/components/explorer/types'
import { HealthTab } from '@/components/health/HealthTab'
import { TaskKanbanBoard } from '@/components/kanban/TaskKanbanBoard'
import { CreateTaskDialog } from '@/components/tasks/CreateTaskDialog'
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

export function ProjectDetailClient() {
  const params = useParams()
  const searchParams = useSearchParams()
  const router = useRouter()
  const projectId = params.id as string

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

  // Update URL when explorer type changes (without full navigation)
  const handleExplorerTypeChange = (type: ExplorerType) => {
    setExplorerType(type)
    const newUrl = `/projects/${projectId}?tab=explorer&type=${type}`
    router.replace(newUrl, { scroll: false })
  }

  // Auto-open task from URL query param
  const urlTaskId = searchParams.get('task')

  // View mode (board | table) for unified tasks tab
  const { viewMode, setViewMode } = useViewMode(projectId)

  // Kanban state
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(urlTaskId)
  const [selectedTask, setSelectedTask] = useState<Task | null>(null)
  const [modalOpen, setModalOpen] = useState(!!urlTaskId)
  const [createTaskDialogOpen, setCreateTaskDialogOpen] = useState(false)
  const [escalationOpen, setEscalationOpen] = useState(false)
  const [escalationTask, setEscalationTask] = useState<Task | null>(null)

  // Handle URL task param changes
  useEffect(() => {
    if (urlTaskId) {
      setSelectedTaskId(urlTaskId)
      setModalOpen(true)
    }
  }, [urlTaskId])

  const {
    data: project,
    isLoading,
    error,
  } = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => fetchProject(projectId),
  })

  // Tasks for Kanban (fetch with feature context)
  const { data: kanbanTasksData, refetch: refetchKanbanTasks } = useQuery({
    queryKey: ['tasks-kanban', projectId],
    queryFn: () => fetchTasks(projectId, { include: 'feature', limit: 500 }),
    staleTime: 30000,
    enabled: activeTab === 'tasks' && viewMode === 'board',
  })
  const kanbanTasks = kanbanTasksData?.tasks ?? []

  // Kanban handlers
  const handleTaskStatusChange = async (
    taskId: string,
    newStatus: TaskStatus,
  ) => {
    try {
      await updateTaskStatus(projectId, taskId, newStatus)
      refetchKanbanTasks()
    } catch (err) {
      console.error('Failed to update task status:', err)
    }
  }

  const handleTaskClick = (task: Task) => {
    if (task.status === 'blocked') {
      setEscalationTask(task)
      setEscalationOpen(true)
    } else {
      setSelectedTaskId(task.id)
      setSelectedTask(task)
      setModalOpen(true)
    }
  }

  const handleApproveAndResume = async (_message?: string) => {
    if (!escalationTask) return
    await executeTask(projectId, escalationTask.id)
    refetchKanbanTasks()
  }

  const handleTaskUpdate = (task: Task) => {
    setSelectedTask(task)
    refetchKanbanTasks()
  }

  const handleNewTask = () => {
    setCreateTaskDialogOpen(true)
  }

  const handleCreateDialogChange = (open: boolean) => {
    setCreateTaskDialogOpen(open)
    if (!open) {
      // Refetch tasks when dialog closes (after create)
      refetchKanbanTasks()
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
          <h2 className="display text-lg font-semibold text-white mb-2">
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
                  onOpenChange={setModalOpen}
                  onTaskUpdate={handleTaskUpdate}
                  initialTask={selectedTask}
                />
                <CreateTaskDialog
                  open={createTaskDialogOpen}
                  onOpenChange={handleCreateDialogChange}
                  projectId={projectId}
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
