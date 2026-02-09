'use client'

import { CheckCircle2, Loader2, Plus, RefreshCw, Trash2 } from 'lucide-react'
import { usePathname, useRouter, useSearchParams } from 'next/navigation'
import { useCallback, useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import type { Task } from '@/lib/api'
import { cn } from '@/lib/utils'
import { BulkDeleteConfirmDialog } from './BulkDeleteConfirmDialog'
import { DeleteConfirmDialog } from './DeleteConfirmDialog'
import { EnrichmentModal } from './EnrichmentModal'
import { useTaskHandlers } from './hooks/useTaskHandlers'
import { useTaskSelection } from './hooks/useTaskSelection'
import { useTaskSort } from './hooks/useTaskSort'
import { useTasksList } from './hooks/useTasksList'
import { SimpleCreateDialog } from './SimpleCreateDialog'
import { SortIndicator } from './SortIndicator'
import { TaskListRow } from './TaskListRow'
import {
  loadFilters,
  saveFilters,
  TaskFilters,
  type TaskFilterValues,
} from './TaskFilters'
import { TaskModal } from './TaskModal'
import { TaskReviewModal } from './TaskReviewModal'

interface TasksTabProps {
  projectId: string
  initialFilters?: Partial<TaskFilterValues>
}

export function TasksTab({ projectId, initialFilters }: TasksTabProps) {
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const urlTaskId = searchParams.get('task')
  const urlModal = searchParams.get('modal')

  // State
  const [filters, setFilters] = useState<TaskFilterValues>(() => {
    const loaded = loadFilters()
    return { ...loaded, ...initialFilters }
  })
  const [modalTaskId, setModalTaskId] = useState<string | null>(urlTaskId)
  const [modalOpen, setModalOpen] = useState(!!urlTaskId)
  const [selectedTask, setSelectedTask] = useState<Task | null>(null)
  const [showCreate, setShowCreate] = useState(urlModal === 'create-task')
  const [enrichingTask, setEnrichingTask] = useState<Task | null>(null)
  const [reviewingTask, setReviewingTask] = useState<Task | null>(null)

  // Custom hooks
  const { sortField, sortDirection, handleSort, sortTasks } = useTaskSort()
  const { filteredTasks, isLoading, isFetching, refetch } = useTasksList(
    projectId,
    filters,
    sortTasks,
  )
  const {
    selectedTaskIds,
    handleToggleSelect,
    handleToggleSelectAll,
    clearSelection,
  } = useTaskSelection()
  const {
    deleteConfirmTask,
    setDeleteConfirmTask,
    bulkDeleteConfirm,
    setBulkDeleteConfirm,
    deleteMutation,
    bulkDeleteMutation,
    handleTaskUpdated,
  } = useTaskHandlers(projectId)

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

  // Persist filters when they change
  useEffect(() => {
    saveFilters(filters)
  }, [filters])

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
  }, [urlModal])

  // Task lifecycle handlers
  const handleTaskCreated = useCallback(
    (task: Task, mode: 'queue' | 'verify') => {
      if (mode === 'verify' && task.enrichment_status === 'review') {
        setReviewingTask(task)
      } else if (mode === 'queue' && task.enrichment_status === 'enriching') {
        setEnrichingTask(task)
      }
      refetch()
    },
    [refetch],
  )

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

  const handleTaskAccepted = useCallback(
    (acceptedTask: Task) => {
      setReviewingTask(null)
      handleTaskUpdated(acceptedTask)
      refetch()
    },
    [refetch, handleTaskUpdated],
  )

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
      clearSelection()
    }
  }

  const handleBulkDelete = () => {
    if (selectedTaskIds.size > 0) {
      bulkDeleteMutation.mutate(Array.from(selectedTaskIds))
    }
  }

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
                    onChange={() => handleToggleSelectAll(filteredTasks)}
                    className="w-4 h-4 rounded border-slate-600 bg-slate-700 text-phosphor-500 focus:ring-phosphor-500 focus:ring-offset-0 cursor-pointer"
                  />
                </th>
                <th className="w-8 px-2 py-2"></th>
                <th
                  className="px-3 py-2 text-left text-xs font-medium text-slate-400 w-16 cursor-pointer hover:text-slate-200 select-none"
                  onClick={() => handleSort('priority')}
                >
                  Pri
                  <SortIndicator
                    field="priority"
                    currentField={sortField}
                    direction={sortDirection}
                  />
                </th>
                <th
                  className="px-3 py-2 text-left text-xs font-medium text-slate-400 w-20 cursor-pointer hover:text-slate-200 select-none"
                  onClick={() => handleSort('type')}
                >
                  Type
                  <SortIndicator
                    field="type"
                    currentField={sortField}
                    direction={sortDirection}
                  />
                </th>
                <th className="px-3 py-2 text-left text-xs font-medium text-slate-400 w-28">
                  ID
                </th>
                <th
                  className="px-3 py-2 text-left text-xs font-medium text-slate-400 cursor-pointer hover:text-slate-200 select-none"
                  onClick={() => handleSort('title')}
                >
                  Title
                  <SortIndicator
                    field="title"
                    currentField={sortField}
                    direction={sortDirection}
                  />
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
                  <SortIndicator
                    field="status"
                    currentField={sortField}
                    direction={sortDirection}
                  />
                </th>
                <th
                  className="px-3 py-2 text-left text-xs font-medium text-slate-400 w-24 cursor-pointer hover:text-slate-200 select-none"
                  onClick={() => handleSort('created_at')}
                >
                  Created
                  <SortIndicator
                    field="created_at"
                    currentField={sortField}
                    direction={sortDirection}
                  />
                </th>
                <th className="px-3 py-2 text-left text-xs font-medium text-slate-400 w-16">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody>
              {filteredTasks.map((task) => (
                <TaskListRow
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
                  subtasks={[]}
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

      {/* Enrichment Progress Modal */}
      {enrichingTask && (
        <EnrichmentModal
          projectId={projectId}
          task={enrichingTask}
          onComplete={handleEnrichmentComplete}
          onError={(err) => {
            console.error('Enrichment error:', err)
            setEnrichingTask(null)
          }}
          onDismiss={() => setEnrichingTask(null)}
        />
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
        <DeleteConfirmDialog
          task={deleteConfirmTask}
          isDeleting={deleteMutation.isPending}
          isError={deleteMutation.isError}
          onConfirm={handleDeleteConfirm}
          onCancel={() => setDeleteConfirmTask(null)}
        />
      )}

      {/* Bulk Delete Confirmation Dialog */}
      {bulkDeleteConfirm && (
        <BulkDeleteConfirmDialog
          taskIds={selectedTaskIds}
          isDeleting={bulkDeleteMutation.isPending}
          isError={bulkDeleteMutation.isError}
          onConfirm={handleBulkDelete}
          onCancel={() => setBulkDeleteConfirm(false)}
        />
      )}
    </div>
  )
}
