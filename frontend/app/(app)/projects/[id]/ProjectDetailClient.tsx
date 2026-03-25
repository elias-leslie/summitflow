'use client'

import { useQuery } from '@tanstack/react-query'
import { AlertCircle, ExternalLink, Settings2 } from 'lucide-react'
import Link from 'next/link'
import { useParams, usePathname, useRouter, useSearchParams } from 'next/navigation'
import { useCallback, useEffect, useState } from 'react'
import { toast } from 'sonner'
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

const TAB_COPY: Record<TabId, { label: string; description: string }> = {
  tasks: {
    label: 'Execution board',
    description:
      'Drive planning and delivery with board and table views that keep momentum visible.',
  },
  explorer: {
    label: 'Code intelligence',
    description:
      'Inspect indexed code structure, scan coverage, and precision-search the project surface.',
  },
  health: {
    label: 'Health and quality',
    description:
      'Monitor quality gate signals, runtime health, and the operational pressure around this project.',
  },
}

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
        <div className="card-elevated p-10 text-center max-w-md relative overflow-hidden">
          <div className="absolute top-0 left-1/2 -translate-x-1/2 w-64 h-32 bg-rose-500/6 rounded-full blur-3xl pointer-events-none" />
          <div className="relative">
            <div className="w-16 h-16 mx-auto mb-5 rounded-2xl bg-rose-500/10 border border-rose-500/20 flex items-center justify-center">
              <AlertCircle className="w-8 h-8 text-rose-400" />
            </div>
            <h2 className="display text-xl font-bold text-slate-100 mb-2 tracking-tight">
              Project Not Found
            </h2>
            <p className="text-sm text-slate-400 mb-8 leading-relaxed">
              The project you&apos;re looking for doesn&apos;t exist or
              couldn&apos;t be loaded.
            </p>
            <Link href="/" className="btn-primary inline-flex items-center gap-2">
              Back to Dashboard
            </Link>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="h-full flex flex-col">
      <div className="flex-none border-b border-slate-800/80 bg-slate-950/55 backdrop-blur-sm">
        <div className="mx-auto w-full max-w-[1600px] px-4 py-3 md:px-5">
          <div className="panel-glass px-4 py-3 md:px-5 md:py-3.5">
            <div className="flex flex-col gap-3 xl:flex-row xl:items-end xl:justify-between">
              <div className="space-y-2.5">
                <div className="eyebrow">Project cockpit</div>
                <div className="flex flex-wrap items-center gap-2.5">
                  <h1 className="display text-lg font-semibold tracking-tight text-slate-100 sm:text-xl xl:text-2xl">
                    {project.name}
                  </h1>
                  <span className="rounded-full border border-slate-700/60 bg-slate-950/72 px-3 py-1 text-[10px] uppercase tracking-[0.16em] text-slate-300">
                    {TAB_COPY[activeTab].label}
                  </span>
                </div>
                <p className="max-w-3xl text-sm leading-relaxed text-slate-300">
                  {TAB_COPY[activeTab].description}
                </p>
                <div className="flex flex-wrap items-center gap-2 text-[11px]">
                  <span className="rounded-full border border-slate-700/60 bg-slate-950/72 px-3 py-1.5 font-mono text-slate-300">
                    {project.id}
                  </span>
                  <span
                    className={project.health_status === 'healthy'
                      ? 'rounded-full border border-emerald-500/18 bg-emerald-500/10 px-3 py-1.5 uppercase tracking-[0.16em] text-emerald-300'
                      : 'rounded-full border border-amber-500/18 bg-amber-500/10 px-3 py-1.5 uppercase tracking-[0.16em] text-amber-300'}
                  >
                    {project.health_status === 'healthy' ? 'healthy service' : 'monitoring'}
                  </span>
                  <span className={project.root_path
                    ? 'rounded-full border border-phosphor-500/18 bg-phosphor-500/10 px-3 py-1.5 text-phosphor-300'
                    : 'rounded-full border border-amber-500/18 bg-amber-500/10 px-3 py-1.5 text-amber-300'}>
                    {project.root_path ? 'root path configured' : 'root path missing'}
                  </span>
                  <a
                    href={project.base_url}
                    target="_blank"
                    rel="noreferrer"
                    className="max-w-full truncate rounded-full border border-slate-700/60 bg-slate-950/72 px-3 py-1.5 font-mono text-slate-300 transition-colors hover:text-phosphor-300"
                    title={project.base_url}
                  >
                    {project.base_url}
                  </a>
                </div>
              </div>

              <div className="flex flex-wrap gap-2 xl:justify-end">
                <a
                  href={project.base_url}
                  target="_blank"
                  rel="noreferrer"
                  className="btn-secondary inline-flex items-center gap-2 px-4 py-1.5 text-sm"
                >
                  <ExternalLink className="h-4 w-4" />
                  Open app
                </a>
                <Link
                  href={`/projects/${project.id}/settings`}
                  className="btn-secondary inline-flex items-center gap-2 px-4 py-1.5 text-sm"
                >
                  <Settings2 className="h-4 w-4" />
                  Settings
                </Link>
              </div>
            </div>
          </div>
        </div>
      </div>

      <section className="flex-1 overflow-hidden">
        {activeTab === 'tasks' && (
          <div className="h-full overflow-auto p-3 sm:p-4 space-y-4">
            <TasksViewToolbar
              viewMode={viewMode}
              onViewModeChange={setViewMode}
              onNewTask={handleNewTask}
            />
            {viewMode === 'board' ? (
              <>
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
          <div className="h-full overflow-auto p-3 sm:p-4">
            <ExplorerTab
              projectId={projectId}
              initialType={explorerType}
              onTypeChange={handleExplorerTypeChange}
            />
          </div>
        )}
        {activeTab === 'health' && (
          <div className="h-full overflow-auto p-3 sm:p-4">
            <HealthTab projectId={projectId} />
          </div>
        )}
      </section>
    </div>
  )
}
