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

import { useState } from 'react'
import type { TaskStatus, TaskType } from '@/lib/api'
import { CreateTaskDialog } from './CreateTaskDialog'
import { useIssueTasks } from './hooks/useIssueTasks'
import { ReadyWorkSection } from './ReadyWorkSection'
import { TaskStats } from './TaskStats'
import { TasksTable } from './TasksTable'
import { TasksTableHeader } from './TasksTableHeader'

interface IssueTasksTabProps {
  projectId: string
}

export function IssueTasksTab({ projectId }: IssueTasksTabProps) {
  const [statusFilter, setStatusFilter] = useState<
    'all' | 'pending' | 'completed'
  >('pending')
  const [typeFilter, setTypeFilter] = useState<TaskType | 'all'>('all')
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [showCreate, setShowCreate] = useState(false)

  const { readyTasks, tasks, isLoading, refetch, updateStatus, isUpdating } =
    useIssueTasks(projectId, statusFilter, typeFilter)

  const handleToggleExpand = (taskId: string) => {
    setExpandedId(expandedId === taskId ? null : taskId)
  }

  const handleTaskClick = (taskId: string) => {
    setExpandedId(expandedId === taskId ? null : taskId)
  }

  const handleStatusChange = (taskId: string, status: TaskStatus) => {
    updateStatus({ taskId, status })
  }

  // Count stats
  const pendingCount = tasks.filter((t) => t.status === 'pending').length
  const runningCount = tasks.filter((t) => t.status === 'running').length
  const completedCount = tasks.filter((t) => t.status === 'completed').length

  return (
    <div className="space-y-6">
      {/* Stats */}
      <TaskStats
        pendingCount={pendingCount}
        runningCount={runningCount}
        completedCount={completedCount}
        totalCount={tasks.length}
      />

      {/* Ready Work Section */}
      <ReadyWorkSection tasks={readyTasks} onTaskClick={handleTaskClick} />

      {/* All Tasks Section */}
      <div className="card">
        <TasksTableHeader
          statusFilter={statusFilter}
          typeFilter={typeFilter}
          onStatusFilterChange={setStatusFilter}
          onTypeFilterChange={setTypeFilter}
          onRefresh={() => refetch()}
          onCreateTask={() => setShowCreate(true)}
          isLoading={isLoading}
        />

        <TasksTable
          tasks={tasks}
          isLoading={isLoading}
          expandedId={expandedId}
          onToggleExpand={handleToggleExpand}
          onStatusChange={handleStatusChange}
          isUpdating={isUpdating}
          projectId={projectId}
        />
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
