"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import {
  CheckCircle2,
  Edit2,
  Save,
  X,
  Play,
  Loader2,
  FastForward,
  Package,
  Bug,
  CheckSquare,
  Link2,
  ExternalLink,
  Square,
  Clock,
  Bot,
  ChevronDown,
  ChevronRight,
} from "lucide-react";

import { Dialog, DialogContent, DialogClose } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { ObjectiveSection } from "@/components/tasks/ObjectiveSection";
import { SubtasksSection } from "@/components/tasks/SubtasksSection";
import { CriteriaProgress } from "@/components/tasks/CriteriaProgress";
import {
  fetchTask,
  getSubtasksWithSteps,
  updateTask,
  updateTaskStatus,
  updateSubtask,
  executeTask,
  type Task,
  type Subtask,
  type TaskStatus,
  type TaskType,
} from "@/lib/api/tasks";
import { ExecutionTimeline } from "@/components/tasks/ExecutionTimeline";
import { ExecutionBadges } from "@/components/tasks/ExecutionBadges";

// ============================================================================
// Collapsible Section Component
// ============================================================================

interface CollapsibleSectionProps {
  title: string;
  isOpen: boolean;
  onToggle: () => void;
  children: React.ReactNode;
  className?: string;
  testId?: string;
}

function CollapsibleSection({
  title,
  isOpen,
  onToggle,
  children,
  className = "",
  testId,
}: CollapsibleSectionProps) {
  return (
    <div className={className}>
      <button
        onClick={onToggle}
        className="flex items-center gap-2 w-full text-left text-sm font-medium text-slate-400 hover:text-slate-300 transition-colors py-1"
        data-testid={testId}
      >
        {isOpen ? (
          <ChevronDown className="h-4 w-4" />
        ) : (
          <ChevronRight className="h-4 w-4" />
        )}
        {title}
      </button>
      {isOpen && <div className="mt-2">{children}</div>}
    </div>
  );
}

// ============================================================================
// Types
// ============================================================================

interface TaskModalProps {
  taskId: string | null;
  projectId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onTaskUpdate?: (task: Task) => void;
  /** Initial task data to avoid refetch if available */
  initialTask?: Task | null;
}

// ============================================================================
// Priority Colors
// ============================================================================

const priorityColors: Record<
  number,
  { bg: string; text: string; border: string }
> = {
  0: {
    bg: "bg-rose-500/30",
    text: "text-rose-300",
    border: "border-rose-500/40",
  },
  1: {
    bg: "bg-orange-500/20",
    text: "text-orange-400",
    border: "border-orange-500/30",
  },
  2: {
    bg: "bg-amber-500/20",
    text: "text-amber-400",
    border: "border-amber-500/30",
  },
  3: {
    bg: "bg-blue-500/20",
    text: "text-blue-400",
    border: "border-blue-500/30",
  },
  4: {
    bg: "bg-slate-500/20",
    text: "text-slate-400",
    border: "border-slate-500/30",
  },
};

// ============================================================================
// Task Type Configuration
// ============================================================================

const taskTypeConfig: Record<
  TaskType,
  { icon: React.ReactNode; label: string; className: string }
> = {
  feature: {
    icon: <Package className="h-4 w-4" />,
    label: "Feature",
    className: "bg-purple-500/20 text-purple-400 border-purple-500/30",
  },
  bug: {
    icon: <Bug className="h-4 w-4" />,
    label: "Bug",
    className: "bg-red-500/20 text-red-400 border-red-500/30",
  },
  task: {
    icon: <CheckSquare className="h-4 w-4" />,
    label: "Task",
    className: "bg-blue-500/20 text-blue-400 border-blue-500/30",
  },
};

// ============================================================================
// Status Configuration
// ============================================================================

const statusConfig: Record<
  TaskStatus,
  { label: string; className: string; icon?: React.ReactNode }
> = {
  pending: {
    label: "Pending",
    className: "bg-slate-500/20 text-slate-400 border-slate-500/30",
  },
  running: {
    label: "Running",
    className: "bg-blue-500/20 text-blue-400 border-blue-500/30",
    icon: <Loader2 className="h-3 w-3 animate-spin" />,
  },
  paused: {
    label: "Paused",
    className: "bg-amber-500/20 text-amber-400 border-amber-500/30",
    icon: <Clock className="h-3 w-3" />,
  },
  blocked: {
    label: "Blocked",
    className: "bg-red-500/20 text-red-400 border-red-500/30",
  },
  pr_created: {
    label: "PR Created",
    className: "bg-purple-500/20 text-purple-400 border-purple-500/30",
  },
  ai_reviewing: {
    label: "AI Reviewing",
    className: "bg-cyan-500/20 text-cyan-400 border-cyan-500/30",
    icon: <Loader2 className="h-3 w-3 animate-spin" />,
  },
  human_review: {
    label: "Human Review",
    className: "bg-orange-500/20 text-orange-400 border-orange-500/30",
  },
  completed: {
    label: "Completed",
    className: "bg-phosphor-500/20 text-phosphor-400 border-phosphor-500/30",
    icon: <CheckCircle2 className="h-3 w-3" />,
  },
  failed: {
    label: "Failed",
    className: "bg-red-500/20 text-red-400 border-red-500/30",
  },
  cancelled: {
    label: "Cancelled",
    className: "bg-slate-500/20 text-slate-400 border-slate-500/30",
  },
};

// ============================================================================
// Task Modal Component
// ============================================================================

export function TaskModal({
  taskId,
  projectId,
  open,
  onOpenChange,
  onTaskUpdate,
  initialTask,
}: TaskModalProps) {
  // Task data state
  const [task, setTask] = useState<Task | null>(initialTask || null);
  const [subtasks, setSubtasks] = useState<Subtask[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isLoadingSubtasks, setIsLoadingSubtasks] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Edit state
  const [isEditing, setIsEditing] = useState(false);
  const [editTitle, setEditTitle] = useState("");
  const [editDescription, setEditDescription] = useState("");

  // Execution state
  const [isExecuting, setIsExecuting] = useState(false);
  const [isStopping, setIsStopping] = useState(false);
  const [executionError, setExecutionError] = useState<string | null>(null);
  const [isTogglingAutonomous, setIsTogglingAutonomous] = useState(false);

  // Collapsible section state (all collapsed by default)
  const [descriptionOpen, setDescriptionOpen] = useState(false);
  const [subtasksOpen, setSubtasksOpen] = useState(false);
  const [timelineOpen, setTimelineOpen] = useState(false);

  // Fetch task when modal opens
  useEffect(() => {
    if (open && taskId) {
      // Use initial task if available and matches ID
      if (initialTask && initialTask.id === taskId) {
        setTask(initialTask);
        setIsLoading(false);
      } else {
        setIsLoading(true);
        setError(null);
        fetchTask(projectId, taskId)
          .then((data) => {
            setTask(data);
          })
          .catch((err) => {
            console.error("Failed to fetch task:", err);
            setError("Failed to load task details");
          })
          .finally(() => {
            setIsLoading(false);
          });
      }
    }
  }, [open, taskId, projectId, initialTask]);

  // Fetch subtasks when task is loaded
  useEffect(() => {
    if (open && task) {
      setIsLoadingSubtasks(true);
      getSubtasksWithSteps(projectId, task.id)
        .then((response) => {
          setSubtasks(response.subtasks);
        })
        .catch((err) => {
          console.error("Failed to fetch subtasks:", err);
          setSubtasks([]);
        })
        .finally(() => {
          setIsLoadingSubtasks(false);
        });
    }
  }, [open, task, projectId]);

  // Reset state when modal closes
  useEffect(() => {
    if (!open) {
      setIsEditing(false);
      setEditTitle("");
      setEditDescription("");
      setError(null);
      // Reset collapsible sections to collapsed
      setDescriptionOpen(false);
      setSubtasksOpen(false);
      setTimelineOpen(false);
    }
  }, [open]);

  // Edit handlers
  const handleEditStart = useCallback(() => {
    if (!task) return;
    setEditTitle(task.title);
    setEditDescription(task.description || "");
    setIsEditing(true);
  }, [task]);

  const handleEditCancel = useCallback(() => {
    setIsEditing(false);
    setEditTitle("");
    setEditDescription("");
  }, []);

  const handleEditSave = useCallback(async () => {
    if (!task) return;
    try {
      const updated = await updateTask(projectId, task.id, {
        title: editTitle,
        description: editDescription,
      });
      setTask(updated);
      onTaskUpdate?.(updated);
      setIsEditing(false);
    } catch (err) {
      console.error("Failed to update task:", err);
    }
  }, [task, projectId, editTitle, editDescription, onTaskUpdate]);

  // Status change handlers
  const handleStatusChange = useCallback(
    async (newStatus: TaskStatus) => {
      if (!task) return;
      try {
        const updated = await updateTaskStatus(projectId, task.id, newStatus);
        setTask(updated);
        onTaskUpdate?.(updated);
      } catch (err) {
        console.error("Failed to update status:", err);
      }
    },
    [task, projectId, onTaskUpdate],
  );

  // Subtask toggle handler
  const handleSubtaskToggle = useCallback(
    async (subtaskId: string, passes: boolean) => {
      if (!task) return;
      try {
        const updated = await updateSubtask(
          projectId,
          task.id,
          subtaskId,
          passes,
        );
        setSubtasks((prev) =>
          prev.map((s) =>
            s.subtask_id === subtaskId ? { ...s, ...updated } : s,
          ),
        );
      } catch (err) {
        console.error("Failed to update subtask:", err);
        throw err;
      }
    },
    [task, projectId],
  );

  // Start execution handler
  const handleStartExecution = useCallback(async () => {
    if (!task) return;
    setIsExecuting(true);
    setExecutionError(null);
    try {
      await executeTask(projectId, task.id);
      // Refetch task to get updated status
      const updated = await fetchTask(projectId, task.id);
      setTask(updated);
      onTaskUpdate?.(updated);
    } catch (err) {
      console.error("Failed to start execution:", err);
      setExecutionError(
        err instanceof Error ? err.message : "Failed to start execution",
      );
    } finally {
      setIsExecuting(false);
    }
  }, [task, projectId, onTaskUpdate]);

  // Stop execution handler (sends signal via WebSocket)
  const handleStopExecution = useCallback(async () => {
    if (!task) return;
    setIsStopping(true);
    // Send stop signal - the WebSocket connection in ExecutionTimeline will handle this
    // For now, we just update the status to paused
    try {
      const updated = await updateTaskStatus(projectId, task.id, "paused");
      setTask(updated);
      onTaskUpdate?.(updated);
    } catch (err) {
      console.error("Failed to stop execution:", err);
    } finally {
      setIsStopping(false);
    }
  }, [task, projectId, onTaskUpdate]);

  // Objective edit handler
  const handleObjectiveEdit = useCallback(
    async (newObjective: string) => {
      if (!task) return;
      // Note: Would need a separate API for objective
      onTaskUpdate?.({ ...task, objective: newObjective });
    },
    [task, onTaskUpdate],
  );

  // Toggle autonomous flag
  const handleToggleAutonomous = useCallback(async () => {
    if (!task) return;
    setIsTogglingAutonomous(true);
    try {
      const updated = await updateTask(projectId, task.id, {
        autonomous: !task.autonomous,
      });
      setTask(updated);
      onTaskUpdate?.(updated);
    } catch (err) {
      console.error("Failed to toggle autonomous:", err);
    } finally {
      setIsTogglingAutonomous(false);
    }
  }, [task, projectId, onTaskUpdate]);

  // Don't render if no task ID
  if (!taskId) return null;

  // Get config values
  const typeConfig = task
    ? taskTypeConfig[task.task_type] || taskTypeConfig.task
    : taskTypeConfig.task;
  const colors = task
    ? priorityColors[task.priority] || priorityColors[2]
    : priorityColors[2];
  const status = task
    ? statusConfig[task.status] || statusConfig.pending
    : statusConfig.pending;

  // Capability context
  const capability = task?.capability;
  const hasCriteria = capability && capability.criteria_total > 0;
  const allPassed =
    hasCriteria && capability.criteria_passed === capability.criteria_total;
  const progressPct = hasCriteria
    ? (capability.criteria_passed / capability.criteria_total) * 100
    : 0;

  // Status checks for action buttons
  const isRunning = task?.status === "running";
  const isPaused = task?.status === "paused";
  const isCompleted = task?.status === "completed";
  const isPending = task?.status === "pending";
  const isHumanReview = task?.status === "human_review";
  const isAiReviewing = task?.status === "ai_reviewing";

  // Show timeline when task is in an active execution state
  const showTimeline = isRunning || isPaused || isAiReviewing;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="w-full max-w-2xl max-h-[90vh] overflow-hidden flex flex-col"
        data-testid="task-modal"
      >
        {/* Close button */}
        <DialogClose onClose={() => onOpenChange(false)} />

        {/* Loading state */}
        {isLoading && (
          <div className="flex items-center justify-center py-20">
            <Loader2 className="w-8 h-8 animate-spin text-slate-500" />
          </div>
        )}

        {/* Error state */}
        {error && !isLoading && (
          <div className="p-6">
            <div className="p-4 bg-red-950/30 border border-red-800/30 rounded-lg">
              <p className="text-sm text-red-400">{error}</p>
            </div>
          </div>
        )}

        {/* Task content */}
        {task && !isLoading && !error && (
          <>
            {/* Header */}
            <div className="border-b border-slate-700 px-6 py-4">
              <div className="flex items-center gap-2 mb-2 flex-wrap">
                <span className="mono text-sm text-slate-500">{task.id}</span>
                <span
                  className={`text-xs px-1.5 py-0.5 rounded border mono font-medium ${colors.bg} ${colors.text} ${colors.border}`}
                >
                  P{task.priority}
                </span>
                <span
                  className={`text-xs px-1.5 py-0.5 rounded border flex items-center gap-1 ${typeConfig.className}`}
                >
                  {typeConfig.icon}
                  {typeConfig.label}
                </span>
                <span
                  className={`text-xs px-1.5 py-0.5 rounded border flex items-center gap-1 ${status.className}`}
                >
                  {status.icon}
                  {status.label}
                </span>
                {/* Execution metadata badges (model, cost, retries) */}
                <ExecutionBadges task={task} />
              </div>
              {isEditing ? (
                <Input
                  value={editTitle}
                  onChange={(e) => setEditTitle(e.target.value)}
                  className="text-lg font-semibold"
                  autoFocus
                />
              ) : (
                <h2 className="display text-lg font-semibold text-white">
                  {task.title}
                </h2>
              )}
            </div>

            {/* Scrollable body */}
            <div className="flex-1 overflow-y-auto px-6 py-4 space-y-6">
              {/* Execution Error */}
              {executionError && (
                <div className="p-3 bg-red-950/30 border border-red-800/30 rounded-lg mb-4">
                  <p className="text-sm text-red-400">{executionError}</p>
                </div>
              )}

              {/* Action Buttons */}
              <div className="flex items-center gap-2 flex-wrap">
                {isPending && (
                  <Button
                    variant="outline"
                    className="gap-2"
                    onClick={handleStartExecution}
                    disabled={isExecuting}
                  >
                    {isExecuting ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Play className="h-4 w-4" />
                    )}
                    {isExecuting ? "Starting..." : "Start Execution"}
                  </Button>
                )}
                {isPaused && (
                  <Button
                    variant="outline"
                    className="gap-2 border-amber-500/30 text-amber-400 hover:bg-amber-500/10"
                    onClick={handleStartExecution}
                    disabled={isExecuting}
                  >
                    {isExecuting ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <FastForward className="h-4 w-4" />
                    )}
                    {isExecuting ? "Resuming..." : "Continue"}
                  </Button>
                )}
                {isRunning && (
                  <>
                    <Button
                      variant="outline"
                      className="gap-2 border-blue-500/30 text-blue-400"
                      disabled
                    >
                      <Loader2 className="h-4 w-4 animate-spin" />
                      Executing...
                    </Button>
                    <Button
                      variant="outline"
                      className="gap-2 border-red-500/30 text-red-400 hover:bg-red-500/10"
                      onClick={handleStopExecution}
                      disabled={isStopping}
                    >
                      <Square className="h-4 w-4" />
                      {isStopping ? "Stopping at next checkpoint..." : "Stop"}
                    </Button>
                  </>
                )}
                {isHumanReview && (
                  <>
                    <Button
                      variant="outline"
                      className="gap-2 border-phosphor-500/30 text-phosphor-400 hover:bg-phosphor-500/10"
                      onClick={() => handleStatusChange("running")}
                    >
                      <CheckCircle2 className="h-4 w-4" />
                      Approve
                    </Button>
                    <Button
                      variant="outline"
                      className="gap-2 border-amber-500/30 text-amber-400 hover:bg-amber-500/10"
                      onClick={() => handleStatusChange("pending")}
                    >
                      <Edit2 className="h-4 w-4" />
                      Request Changes
                    </Button>
                  </>
                )}
                {isCompleted && (
                  <Button
                    variant="outline"
                    className="gap-2 border-phosphor-500/30 text-phosphor-400"
                    disabled
                  >
                    <CheckCircle2 className="h-4 w-4" />
                    Completed
                  </Button>
                )}
                {isAiReviewing && (
                  <Button
                    variant="outline"
                    className="gap-2 border-cyan-500/30 text-cyan-400"
                    disabled
                  >
                    <Loader2 className="h-4 w-4 animate-spin" />
                    AI Reviewing...
                  </Button>
                )}
                {/* Autonomous Toggle */}
                <Button
                  variant="outline"
                  className={`gap-2 ${
                    task.autonomous
                      ? "border-purple-500/30 text-purple-400 bg-purple-500/10"
                      : "border-slate-600 text-slate-400"
                  }`}
                  onClick={handleToggleAutonomous}
                  disabled={isTogglingAutonomous || isRunning}
                  title={
                    task.autonomous
                      ? "Autonomous execution enabled - task will be picked up by auto-exec when enabled"
                      : "Click to enable autonomous execution for this task"
                  }
                >
                  {isTogglingAutonomous ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Bot className="h-4 w-4" />
                  )}
                  {task.autonomous ? "Autonomous" : "Manual"}
                </Button>
                <div className="ml-auto flex items-center gap-2">
                  {isEditing ? (
                    <>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={handleEditCancel}
                      >
                        <X className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="primary"
                        size="sm"
                        onClick={handleEditSave}
                      >
                        <Save className="h-4 w-4" />
                      </Button>
                    </>
                  ) : (
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={handleEditStart}
                    >
                      <Edit2 className="h-4 w-4" />
                    </Button>
                  )}
                </div>
              </div>

              {/* Objective Section - Always visible at top */}
              <ObjectiveSection
                objective={task.objective}
                onEdit={handleObjectiveEdit}
              />

              {/* Description - Collapsible, collapsed by default */}
              <CollapsibleSection
                title="Description"
                isOpen={descriptionOpen}
                onToggle={() => setDescriptionOpen(!descriptionOpen)}
                testId="description-toggle"
              >
                {isEditing ? (
                  <Textarea
                    value={editDescription}
                    onChange={(e) => setEditDescription(e.target.value)}
                    rows={3}
                    placeholder="Enter task description..."
                  />
                ) : (
                  <p className="text-sm text-slate-300">
                    {task.description || (
                      <span className="italic text-slate-500">
                        No description
                      </span>
                    )}
                  </p>
                )}
              </CollapsibleSection>

              {/* Linked Capability */}
              {capability && (
                <div>
                  <div className="flex items-center justify-between mb-3">
                    <h3 className="text-sm font-medium text-slate-400 flex items-center gap-2">
                      <Link2 className="h-4 w-4" />
                      Linked Capability
                    </h3>
                    <Link
                      href={`/projects/${projectId}/components`}
                      className="text-xs text-phosphor-400 hover:text-phosphor-300 flex items-center gap-1"
                    >
                      View Capabilities
                      <ExternalLink className="h-3 w-3" />
                    </Link>
                  </div>

                  <div className="rounded-lg border border-slate-700 bg-slate-900/50 p-3">
                    <div className="flex items-center justify-between mb-2">
                      <div>
                        <span className="mono text-xs text-slate-500">
                          {capability.capability_id}
                        </span>
                        <h4 className="text-sm font-medium text-white">
                          {capability.name}
                        </h4>
                      </div>
                    </div>

                    {hasCriteria && (
                      <div className="mt-3">
                        <div className="flex items-center justify-between mb-1.5">
                          <span className="text-xs text-slate-500">
                            Criteria
                          </span>
                          <span
                            className={`text-xs mono font-medium ${allPassed ? "text-phosphor-400" : "text-slate-400"}`}
                          >
                            {capability.criteria_passed}/
                            {capability.criteria_total}
                          </span>
                        </div>
                        <div className="h-1.5 w-full bg-slate-700 rounded-full overflow-hidden">
                          <div
                            className={`h-full transition-all duration-300 ${allPassed ? "bg-phosphor-500" : "bg-blue-500"}`}
                            style={{ width: `${progressPct}%` }}
                          />
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* Criteria Progress */}
              {task.acceptance_criteria &&
                task.acceptance_criteria.length > 0 && (
                  <div>
                    <div className="flex items-center justify-between mb-2">
                      <h3 className="text-sm font-medium text-slate-400">
                        Acceptance Criteria
                      </h3>
                      <CriteriaProgress
                        criteria={task.acceptance_criteria}
                        maxVisible={10}
                      />
                    </div>
                    <span className="text-xs px-2 py-0.5 rounded bg-slate-800 text-slate-400 border border-slate-700">
                      {capability
                        ? `From: ${capability.capability_id}`
                        : "Task-specific"}
                    </span>
                  </div>
                )}

              {/* Subtasks Section - Collapsible, collapsed by default */}
              {isLoadingSubtasks ? (
                <div className="flex items-center justify-center py-4">
                  <Loader2 className="w-5 h-5 animate-spin text-slate-500" />
                </div>
              ) : subtasks.length > 0 ? (
                <CollapsibleSection
                  title={`Subtasks (${subtasks.filter((s) => s.passes).length}/${subtasks.length})`}
                  isOpen={subtasksOpen}
                  onToggle={() => setSubtasksOpen(!subtasksOpen)}
                  testId="subtasks-toggle"
                >
                  <SubtasksSection
                    projectId={projectId}
                    taskId={task.id}
                    subtasks={subtasks}
                    onTogglePass={handleSubtaskToggle}
                  />
                </CollapsibleSection>
              ) : (
                <CollapsibleSection
                  title="Subtasks"
                  isOpen={subtasksOpen}
                  onToggle={() => setSubtasksOpen(!subtasksOpen)}
                  testId="subtasks-toggle"
                >
                  <p className="text-sm text-slate-500 italic">
                    No subtasks defined. Run /plan_it to add subtasks.
                  </p>
                </CollapsibleSection>
              )}

              {/* Execution Timeline - Collapsible at bottom, collapsed by default */}
              {showTimeline && (
                <CollapsibleSection
                  title="Execution Timeline"
                  isOpen={timelineOpen}
                  onToggle={() => setTimelineOpen(!timelineOpen)}
                  testId="timeline-toggle"
                >
                  <ExecutionTimeline
                    taskId={task.id}
                    autoConnect={isRunning || isAiReviewing}
                    showChatInput={true}
                    chatEnabled={isRunning}
                    className="border border-slate-700 rounded-lg overflow-hidden"
                  />
                </CollapsibleSection>
              )}

              {/* Labels */}
              {task.labels && task.labels.length > 0 && (
                <div>
                  <h3 className="text-sm font-medium text-slate-400 mb-2">
                    Labels
                  </h3>
                  <div className="flex flex-wrap gap-2">
                    {task.labels.map((label) => (
                      <span
                        key={label}
                        className="text-xs px-2 py-1 rounded bg-slate-700/50 text-slate-400 border border-slate-600"
                      >
                        {label}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Metadata */}
              <div className="text-xs text-slate-500 space-y-1 pt-4 border-t border-slate-800">
                <p>
                  Status: <span className="text-slate-300">{task.status}</span>
                </p>
                {task.created_at && (
                  <p>
                    Created: {new Date(task.created_at).toLocaleDateString()}
                  </p>
                )}
                {task.started_at && (
                  <p>
                    Started: {new Date(task.started_at).toLocaleDateString()}
                  </p>
                )}
                {task.completed_at && (
                  <p>
                    Completed:{" "}
                    {new Date(task.completed_at).toLocaleDateString()}
                  </p>
                )}
              </div>
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
