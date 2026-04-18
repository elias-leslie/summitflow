'use client'

import clsx from 'clsx'
import {
  Activity,
  CheckCircle2,
  Circle,
  FileText,
  GitBranch,
  Loader2,
  Terminal,
  XCircle,
} from 'lucide-react'
import { motion } from 'motion/react'
import { useState } from 'react'
import { AgentObservabilityTimeline } from '@/components/tasks/AgentObservabilityTimeline'
import { CheckpointStatus } from '@/components/tasks/CheckpointStatus'
import { CriteriaProgress } from '@/components/tasks/CriteriaProgress'
import { ExecutionTimeline } from '@/components/tasks/ExecutionTimeline'
import { LinkedCapabilitySection } from '@/components/tasks/LinkedCapabilitySection'
import { NarrationTimeline } from '@/components/tasks/NarrationTimeline'
import { SubtasksSection } from '@/components/tasks/SubtasksSection'
import { TaskLabels } from '@/components/tasks/TaskLabels'
import { TaskMetadata } from '@/components/tasks/TaskMetadata'
import { Textarea } from '@/components/ui/textarea'
import type { Subtask, Task, VerificationResult } from '@/lib/api/tasks'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type TaskModalTab = 'overview' | 'activity' | 'execution' | 'git'

interface TaskModalContentProps {
  task: Task
  projectId: string
  subtasks: Subtask[]
  isLoadingSubtasks: boolean
  subtasksError: string | null
  isEditing: boolean
  editDescription: string
  executionError: string | null
  onEditDescriptionChange: (value: string) => void
  onSubtaskToggle: (subtaskId: string, passes: boolean) => Promise<void>
}

// ---------------------------------------------------------------------------
// Tab configuration
// ---------------------------------------------------------------------------

const TAB_CONFIG = [
  { id: 'overview' as const, label: 'Overview', icon: FileText },
  { id: 'activity' as const, label: 'Activity', icon: Activity },
  { id: 'execution' as const, label: 'Execution', icon: Terminal },
  { id: 'git' as const, label: 'Git', icon: GitBranch },
] as const

/** Does this task have any execution data worth viewing? */
function hasExecutionData(task: Task): boolean {
  return (
    (task.agent_hub_session_ids && task.agent_hub_session_ids.length > 0) ||
    task.status === 'running'
  )
}

function getDefaultTab(task: Task): TaskModalTab {
  if (task.status === 'running') return 'activity'
  return 'overview'
}

function getVisibleTabs(task: Task): TaskModalTab[] {
  const tabs: TaskModalTab[] = ['overview', 'activity']
  if (hasExecutionData(task)) {
    tabs.push('execution')
  }
  if (task.branch_name || task.status === 'running') {
    tabs.push('git')
  }
  return tabs
}

// ---------------------------------------------------------------------------
// Tab bar
// ---------------------------------------------------------------------------

function TabBar({
  tabs,
  activeTab,
  onTabChange,
  task,
}: {
  tabs: TaskModalTab[]
  activeTab: TaskModalTab
  onTabChange: (tab: TaskModalTab) => void
  task: Task
}) {
  const isLive = task.status === 'running'

  return (
    <div className="flex items-center gap-1 px-6 pt-3 pb-0">
      {tabs.map((tabId) => {
        const config = TAB_CONFIG.find((t) => t.id === tabId)!
        const Icon = config.icon
        const isActive = activeTab === tabId

        return (
          <button
            key={tabId}
            type="button"
            onClick={() => onTabChange(tabId)}
            className={clsx(
              'relative flex items-center gap-1.5 px-3 py-2 text-xs font-medium rounded-t-md transition-all duration-200',
              isActive
                ? 'text-slate-100 bg-slate-800/80'
                : 'text-slate-500 hover:text-slate-300 hover:bg-slate-800/30',
            )}
            data-testid={`tab-${tabId}`}
          >
            <Icon className="w-3.5 h-3.5" />
            {config.label}

            {/* Live pulse on Activity tab */}
            {tabId === 'activity' && isLive && !isActive && (
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-phosphor-500 opacity-60" />
                <span className="relative inline-flex rounded-full h-2 w-2 bg-phosphor-400" />
              </span>
            )}

            {/* Active indicator */}
            {isActive && (
              <motion.div
                layoutId="task-tab-indicator"
                className="absolute bottom-0 left-2 right-2 h-[2px] rounded-full bg-phosphor-500"
                transition={{ duration: 0.2, ease: 'easeOut' }}
              />
            )}
          </button>
        )
      })}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Shared components
// ---------------------------------------------------------------------------

function DoneWhenSection({ doneWhen }: { doneWhen: string[] }) {
  if (doneWhen.length === 0) return null

  return (
    <section>
      <h4 className="text-xs font-mono uppercase tracking-wider text-slate-500 mb-2">
        Done When
      </h4>
      <ul className="space-y-1.5">
        {doneWhen.map((criterion, i) => (
          <li key={i} className="flex items-start gap-2 text-sm text-slate-300">
            <Circle className="w-3 h-3 mt-1 text-slate-600 flex-shrink-0" />
            <span className="leading-relaxed">{criterion}</span>
          </li>
        ))}
      </ul>
    </section>
  )
}

function VerificationResultSection({ result }: { result: VerificationResult }) {
  const isPartial = result.partial_merge === true
  const isClean = result.execution_clean === true

  return (
    <section>
      <h4 className="text-xs font-mono uppercase tracking-wider text-slate-500 mb-2">
        Completion Gate
      </h4>
      <div
        className={clsx(
          'p-3 rounded-lg border',
          isPartial
            ? 'bg-amber-950/20 border-amber-800/20'
            : isClean
              ? 'bg-emerald-950/20 border-emerald-800/20'
              : 'bg-slate-800/50 border-slate-700/30',
        )}
      >
        {/* Summary line */}
        <div className="flex items-center gap-2 mb-2">
          {isPartial ? (
            <XCircle className="w-4 h-4 text-amber-400" />
          ) : isClean ? (
            <CheckCircle2 className="w-4 h-4 text-emerald-400" />
          ) : (
            <CheckCircle2 className="w-4 h-4 text-slate-400" />
          )}
          <span
            className={clsx(
              'text-sm font-medium',
              isPartial
                ? 'text-amber-300'
                : isClean
                  ? 'text-emerald-300'
                  : 'text-slate-300',
            )}
          >
            {isPartial
              ? `Partial merge — ${result.passed_count}/${result.subtask_count} subtasks passed`
              : isClean
                ? 'Clean execution'
                : `${result.subtask_count} subtask${result.subtask_count === 1 ? '' : 's'} executed`}
          </span>
        </div>

        {/* Stats */}
        <div className="flex gap-4 text-xs text-slate-500">
          {result.total_self_fix_attempts != null &&
            result.total_self_fix_attempts > 0 && (
              <span>
                {result.total_self_fix_attempts} self-fix
                {result.total_self_fix_attempts === 1 ? '' : 'es'}
              </span>
            )}
          {result.total_supervisor_attempts != null &&
            result.total_supervisor_attempts > 0 && (
              <span>
                {result.total_supervisor_attempts} supervisor intervention
                {result.total_supervisor_attempts === 1 ? '' : 's'}
              </span>
            )}
          {result.total_extensions_granted != null &&
            result.total_extensions_granted > 0 && (
              <span>
                {result.total_extensions_granted} extension
                {result.total_extensions_granted === 1 ? '' : 's'}
              </span>
            )}
        </div>

        {/* Failed subtask details */}
        {isPartial &&
          result.failed_details &&
          result.failed_details.length > 0 && (
            <div className="mt-3 pt-3 border-t border-amber-800/20 space-y-2">
              {result.failed_details.map((detail) => (
                <div key={detail.subtask_id} className="text-xs">
                  <span className="font-mono text-amber-400">
                    {detail.subtask_id}
                  </span>
                  <span className="text-slate-500 ml-2">
                    {detail.failure_reason}
                  </span>
                </div>
              ))}
            </div>
          )}
      </div>
    </section>
  )
}

// ---------------------------------------------------------------------------
// Tab panels
// ---------------------------------------------------------------------------

function OverviewPanel({
  task,
  projectId,
  subtasks,
  isLoadingSubtasks,
  subtasksError,
  isEditing,
  editDescription,
  onEditDescriptionChange,
  onSubtaskToggle,
}: TaskModalContentProps) {
  const capability = task.capability

  return (
    <div className="space-y-5">
      {/* Done When — the success definition */}
      {task.done_when && task.done_when.length > 0 && (
        <DoneWhenSection doneWhen={task.done_when} />
      )}

      {/* Description */}
      <section>
        <h4 className="text-xs font-mono uppercase tracking-wider text-slate-500 mb-2">
          Description
        </h4>
        {isEditing ? (
          <Textarea
            value={editDescription}
            onChange={(e) => onEditDescriptionChange(e.target.value)}
            rows={3}
            placeholder="Enter task description..."
          />
        ) : (
          <p className="text-sm text-slate-300 leading-relaxed">
            {task.description || (
              <span className="italic text-slate-600">No description</span>
            )}
          </p>
        )}
      </section>

      {/* Verification result — shown when task has completion gate output */}
      {task.verification_result && (
        <VerificationResultSection result={task.verification_result} />
      )}

      {/* Acceptance criteria inline */}
      {task.acceptance_criteria && task.acceptance_criteria.length > 0 && (
        <section>
          <div className="flex items-center justify-between mb-2">
            <h4 className="text-xs font-mono uppercase tracking-wider text-slate-500">
              Acceptance Criteria
            </h4>
            <CriteriaProgress
              criteria={task.acceptance_criteria}
              maxVisible={10}
            />
          </div>
          {capability && (
            <span className="text-2xs px-2 py-0.5 rounded bg-slate-800 text-slate-500 border border-slate-700/50">
              From: {capability.capability_id}
            </span>
          )}
        </section>
      )}

      {/* Linked Capability */}
      {capability && (
        <LinkedCapabilitySection
          capability={capability}
          projectId={projectId}
        />
      )}

      {/* Subtasks */}
      <section>
        {isLoadingSubtasks ? (
          <div className="flex items-center justify-center py-6">
            <Loader2 className="w-5 h-5 animate-spin text-slate-600" />
          </div>
        ) : subtasksError ? (
          <div className="p-3 rounded-lg bg-rose-950/20 border border-rose-800/20">
            <p className="text-sm text-rose-400">{subtasksError}</p>
          </div>
        ) : subtasks.length > 0 ? (
          <SubtasksSection
            projectId={projectId}
            taskId={task.id}
            subtasks={subtasks}
            onTogglePass={onSubtaskToggle}
          />
        ) : (
          <div className="p-4 rounded-lg bg-slate-800/30 border border-slate-700/30 text-center">
            <p className="text-sm text-slate-600">No subtasks defined yet</p>
          </div>
        )}
      </section>

      {/* Labels */}
      <TaskLabels labels={task.labels || []} />

      {/* Metadata footer */}
      <TaskMetadata task={task} />
    </div>
  )
}

function ActivityPanel({ task }: { task: Task }) {
  const isLive = task.status === 'running'

  return (
    <div className="space-y-4">
      <NarrationTimeline taskId={task.id} isLive={isLive} pollInterval={5000} />
    </div>
  )
}

function ExecutionPanel({
  task,
  projectId,
}: {
  task: Task
  projectId: string
}) {
  const isRunning = task.status === 'running'
  const [depth, setDepth] = useState<'events' | 'agent'>('events')

  return (
    <div className="space-y-3">
      {/* Depth toggle */}
      <div className="flex items-center gap-1 p-0.5 rounded-md bg-slate-800/50 border border-slate-700/40 w-fit">
        <button
          type="button"
          onClick={() => setDepth('events')}
          className={clsx(
            'px-3 py-1 text-xs rounded transition-all duration-150',
            depth === 'events'
              ? 'bg-slate-700 text-slate-100 shadow-sm'
              : 'text-slate-500 hover:text-slate-300',
          )}
        >
          Event Stream
        </button>
        <button
          type="button"
          onClick={() => setDepth('agent')}
          className={clsx(
            'px-3 py-1 text-xs rounded transition-all duration-150',
            depth === 'agent'
              ? 'bg-slate-700 text-slate-100 shadow-sm'
              : 'text-slate-500 hover:text-slate-300',
          )}
        >
          Agent Detail
        </button>
      </div>

      {depth === 'events' ? (
        <ExecutionTimeline
          taskId={task.id}
          projectId={projectId}
          autoConnect={isRunning}
          showChatInput={true}
          chatEnabled={isRunning}
          className="border border-slate-700/50 rounded-lg overflow-hidden"
        />
      ) : (
        <AgentObservabilityTimeline
          taskId={task.id}
          projectId={projectId}
          isLive={isRunning}
          pollInterval={3000}
          maxHeight="600px"
          className="border border-slate-700/50 rounded-lg overflow-hidden"
        />
      )}
    </div>
  )
}

function GitPanel({ task, projectId }: { task: Task; projectId: string }) {
  return (
    <div className="space-y-4">
      <CheckpointStatus
        taskId={task.id}
        projectId={projectId}
        taskStatus={task.status}
      />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function TaskModalContent(props: TaskModalContentProps) {
  const { task, projectId, executionError } = props
  const [activeTab, setActiveTab] = useState<TaskModalTab>(() =>
    getDefaultTab(task),
  )

  const visibleTabs = getVisibleTabs(task)
  const resolvedTab = visibleTabs.includes(activeTab)
    ? activeTab
    : visibleTabs[0]

  return (
    <div className="flex-1 overflow-hidden flex flex-col">
      {executionError && (
        <div className="mx-6 mt-3 p-3 bg-red-950/30 border border-red-800/30 rounded-lg">
          <p className="text-sm text-red-400">{executionError}</p>
        </div>
      )}

      <TabBar
        tabs={visibleTabs}
        activeTab={resolvedTab}
        onTabChange={setActiveTab}
        task={task}
      />

      <div className="h-px mx-6 bg-gradient-to-r from-transparent via-slate-700 to-transparent" />

      <div className="flex-1 overflow-y-auto px-6 py-4">
        {resolvedTab === 'overview' && <OverviewPanel {...props} />}
        {resolvedTab === 'activity' && <ActivityPanel task={task} />}
        {resolvedTab === 'execution' && (
          <ExecutionPanel task={task} projectId={projectId} />
        )}
        {resolvedTab === 'git' && (
          <GitPanel task={task} projectId={projectId} />
        )}
      </div>
    </div>
  )
}
