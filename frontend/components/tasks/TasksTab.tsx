'use client'

import { useEffect, useState } from 'react'
import { useTaskHandlers } from './hooks/useTaskHandlers'
import { useTaskSelection } from './hooks/useTaskSelection'
import { useTaskSort } from './hooks/useTaskSort'
import { useTasksList } from './hooks/useTasksList'
import { useTasksTabState } from './hooks/useTasksTabState'
import { loadFilters, saveFilters, type TaskFilterValues } from './TaskFilters'
import { TasksTabHeader } from './TasksTabHeader'
import { TasksTabModals } from './TasksTabModals'
import { TasksTabTable } from './TasksTabTable'

interface TasksTabProps {
  projectId: string
  initialFilters?: Partial<TaskFilterValues>
}

export function TasksTab({ projectId, initialFilters }: TasksTabProps) {
  // Filter state
  const [filters, setFilters] = useState<TaskFilterValues>(() => {
    const loaded = loadFilters()
    return { ...loaded, ...initialFilters }
  })

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

  const {
    modalTaskId,
    modalOpen,
    selectedTask,
    showCreate,
    enrichingTask,
    reviewingTask,
    handleTaskCreated,
    handleEnrichmentComplete,
    handleTaskAccepted,
    handleTaskClick,
    handleModalOpenChange,
    handleShowCreateChange,
    handleTaskUpdate,
    setEnrichingTask,
    setReviewingTask,
  } = useTasksTabState({ refetch, handleTaskUpdated })

  // Persist filters when they change
  useEffect(() => {
    saveFilters(filters)
  }, [filters])

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
      <TasksTabHeader
        projectId={projectId}
        filters={filters}
        onFiltersChange={setFilters}
        selectedCount={selectedTaskIds.size}
        isFetching={isFetching}
        onRefresh={refetch}
        onBulkDelete={() => setBulkDeleteConfirm(true)}
      />

      <TasksTabTable
        tasks={filteredTasks}
        isLoading={isLoading}
        sortField={sortField}
        sortDirection={sortDirection}
        onSort={handleSort}
        selectedTaskIds={selectedTaskIds}
        onToggleSelect={handleToggleSelect}
        onToggleSelectAll={handleToggleSelectAll}
        onTaskClick={handleTaskClick}
        onDeleteClick={handleDeleteClick}
      />

      <TasksTabModals
        projectId={projectId}
        modalTaskId={modalTaskId}
        modalOpen={modalOpen}
        selectedTask={selectedTask}
        onModalOpenChange={handleModalOpenChange}
        onTaskUpdate={handleTaskUpdate}
        showCreate={showCreate}
        onShowCreateChange={handleShowCreateChange}
        onTaskCreated={handleTaskCreated}
        enrichingTask={enrichingTask}
        onEnrichmentComplete={handleEnrichmentComplete}
        onEnrichmentError={(err) => {
          console.error('Enrichment error:', err)
          setEnrichingTask(null)
        }}
        onEnrichmentDismiss={() => setEnrichingTask(null)}
        reviewingTask={reviewingTask}
        onReviewOpenChange={(open) => {
          if (!open) setReviewingTask(null)
        }}
        onTaskAccepted={handleTaskAccepted}
        onTaskDiscard={() => setReviewingTask(null)}
        deleteConfirmTask={deleteConfirmTask}
        onDeleteConfirm={handleDeleteConfirm}
        onDeleteCancel={() => setDeleteConfirmTask(null)}
        isDeletingTask={deleteMutation.isPending}
        isDeleteError={deleteMutation.isError}
        bulkDeleteConfirm={bulkDeleteConfirm}
        selectedTaskIds={selectedTaskIds}
        onBulkDeleteConfirm={handleBulkDelete}
        onBulkDeleteCancel={() => setBulkDeleteConfirm(false)}
        isBulkDeleting={bulkDeleteMutation.isPending}
        isBulkDeleteError={bulkDeleteMutation.isError}
      />
    </div>
  )
}
