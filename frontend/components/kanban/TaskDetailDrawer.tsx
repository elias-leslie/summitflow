"use client";

import { useState, useEffect } from "react";
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
} from "lucide-react";

import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetBody, SheetClose } from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { CheckpointViewer, type Checkpoint } from "@/components/tasks/CheckpointViewer";
import { PhaseProgress } from "@/components/tasks/PhaseProgress";
import { ObjectiveSection } from "@/components/tasks/ObjectiveSection";
import { SubtasksSection } from "@/components/tasks/SubtasksSection";
import { CriteriaProgress } from "@/components/tasks/CriteriaProgress";
import { getSubtasks, type Subtask } from "@/lib/api/tasks";
import type { Task, TaskType, TaskStatus } from "@/lib/api";

interface TaskDetailDrawerProps {
  task: Task | null;
  projectId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onStatusChange?: (taskId: string, status: TaskStatus) => void;
  onTaskUpdate?: (taskId: string, updates: Partial<Task>) => void;
  /** Checkpoint for this task's session, if available */
  checkpoint?: Checkpoint | null;
}

// ============================================================================
// Priority Colors
// ============================================================================

const priorityColors: Record<number, { bg: string; text: string; border: string }> = {
  0: { bg: "bg-rose-500/30", text: "text-rose-300", border: "border-rose-500/40" },
  1: { bg: "bg-orange-500/20", text: "text-orange-400", border: "border-orange-500/30" },
  2: { bg: "bg-amber-500/20", text: "text-amber-400", border: "border-amber-500/30" },
  3: { bg: "bg-blue-500/20", text: "text-blue-400", border: "border-blue-500/30" },
  4: { bg: "bg-slate-500/20", text: "text-slate-400", border: "border-slate-500/30" },
};

// ============================================================================
// Task Type Configuration
// ============================================================================

const taskTypeConfig: Record<TaskType, { icon: React.ReactNode; label: string; className: string }> = {
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
// Task Detail Drawer
// ============================================================================

export function TaskDetailDrawer({
  task,
  projectId,
  open,
  onOpenChange,
  onStatusChange,
  onTaskUpdate,
  checkpoint,
}: TaskDetailDrawerProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [editTitle, setEditTitle] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const [subtasks, setSubtasks] = useState<Subtask[]>([]);
  const [isLoadingSubtasks, setIsLoadingSubtasks] = useState(false);

  // Fetch subtasks when drawer opens
  useEffect(() => {
    if (open && task) {
      setIsLoadingSubtasks(true);
      getSubtasks(projectId, task.id)
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

  if (!task) return null;

  const typeConfig = taskTypeConfig[task.task_type] || taskTypeConfig.task;
  const colors = priorityColors[task.priority] || priorityColors[2];

  // Capability context
  const capability = task.capability;
  const hasCriteria = capability && capability.criteria_total > 0;
  const allPassed = hasCriteria && capability.criteria_passed === capability.criteria_total;
  const progressPct = hasCriteria ? (capability.criteria_passed / capability.criteria_total) * 100 : 0;

  // Status checks
  const isRunning = task.status === "running";
  const isPaused = task.status === "paused";
  const isCompleted = task.status === "completed";

  const handleEditStart = () => {
    setEditTitle(task.title);
    setEditDescription(task.description || "");
    setIsEditing(true);
  };

  const handleEditCancel = () => {
    setIsEditing(false);
    setEditTitle("");
    setEditDescription("");
  };

  const handleEditSave = () => {
    onTaskUpdate?.(task.id, {
      title: editTitle,
      description: editDescription,
    });
    setIsEditing(false);
  };

  const handleStart = () => {
    onStatusChange?.(task.id, "running");
  };

  const handleComplete = () => {
    onStatusChange?.(task.id, "completed");
  };

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="max-w-lg">
        <SheetHeader className="relative">
          <SheetClose onClose={() => onOpenChange(false)} />
          <div className="flex items-center gap-2 mb-2 flex-wrap">
            <span className="mono text-sm text-slate-500">{task.id}</span>
            <span className={`text-xs px-1.5 py-0.5 rounded border mono font-medium ${colors.bg} ${colors.text} ${colors.border}`}>
              P{task.priority}
            </span>
            <span className={`text-xs px-1.5 py-0.5 rounded border flex items-center gap-1 ${typeConfig.className}`}>
              {typeConfig.icon}
              {typeConfig.label}
            </span>
          </div>
          {isEditing ? (
            <Input
              value={editTitle}
              onChange={(e) => setEditTitle(e.target.value)}
              className="text-lg font-semibold"
              autoFocus
            />
          ) : (
            <SheetTitle>{task.title}</SheetTitle>
          )}
        </SheetHeader>

        <SheetBody className="space-y-6">
          {/* Action Buttons */}
          <div className="flex items-center gap-2">
            {isPaused ? (
              <Button
                variant="outline"
                className="flex-1 gap-2 border-amber-500/30 text-amber-400 hover:bg-amber-500/10"
                onClick={handleStart}
              >
                <FastForward className="h-4 w-4" />
                Continue
              </Button>
            ) : isRunning ? (
              <Button
                variant="outline"
                className="flex-1 gap-2 border-blue-500/30 text-blue-400"
                disabled
              >
                <Loader2 className="h-4 w-4 animate-spin" />
                Running
              </Button>
            ) : isCompleted ? (
              <Button
                variant="outline"
                className="flex-1 gap-2 border-phosphor-500/30 text-phosphor-400"
                disabled
              >
                <CheckCircle2 className="h-4 w-4" />
                Completed
              </Button>
            ) : (
              <Button
                variant="outline"
                className="flex-1 gap-2"
                onClick={handleStart}
              >
                <Play className="h-4 w-4" />
                Start
              </Button>
            )}
            {isRunning && (
              <Button
                variant="outline"
                className="gap-2 border-phosphor-500/30 text-phosphor-400 hover:bg-phosphor-500/10"
                onClick={handleComplete}
              >
                <CheckCircle2 className="h-4 w-4" />
                Complete
              </Button>
            )}
            {isEditing ? (
              <>
                <Button variant="outline" size="sm" onClick={handleEditCancel}>
                  <X className="h-4 w-4" />
                </Button>
                <Button variant="primary" size="sm" onClick={handleEditSave}>
                  <Save className="h-4 w-4" />
                </Button>
              </>
            ) : (
              <Button variant="outline" size="sm" onClick={handleEditStart}>
                <Edit2 className="h-4 w-4" />
              </Button>
            )}
          </div>

          {/* Description */}
          <div>
            <h3 className="text-sm font-medium text-slate-400 mb-2">Description</h3>
            {isEditing ? (
              <Textarea
                value={editDescription}
                onChange={(e) => setEditDescription(e.target.value)}
                rows={3}
                placeholder="Enter task description..."
              />
            ) : (
              <p className="text-sm text-slate-300">
                {task.description || <span className="italic text-slate-500">No description</span>}
              </p>
            )}
          </div>

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
                    <span className="mono text-xs text-slate-500">{capability.capability_id}</span>
                    <h4 className="text-sm font-medium text-white">{capability.name}</h4>
                  </div>
                </div>

                {/* Criteria Progress */}
                {hasCriteria && (
                  <div className="mt-3">
                    <div className="flex items-center justify-between mb-1.5">
                      <span className="text-xs text-slate-500">Criteria</span>
                      <span className={`text-xs mono font-medium ${allPassed ? "text-phosphor-400" : "text-slate-400"}`}>
                        {capability.criteria_passed}/{capability.criteria_total}
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

          {/* Phase Progress */}
          <PhaseProgress currentPhase={task.current_phase} />

          {/* Objective Section */}
          <ObjectiveSection
            objective={task.objective}
            onEdit={async (newObjective) => {
              // For now, just log - a proper API would be needed
              console.log("Edit objective:", newObjective);
            }}
          />

          {/* Criteria Progress */}
          {task.acceptance_criteria && task.acceptance_criteria.length > 0 && (
            <div>
              <div className="flex items-center justify-between mb-2">
                <h3 className="text-sm font-medium text-slate-400">Acceptance Criteria</h3>
                <CriteriaProgress criteria={task.acceptance_criteria} maxVisible={10} />
              </div>
              {/* Source indicator */}
              <span className="text-xs px-2 py-0.5 rounded bg-slate-800 text-slate-400 border border-slate-700">
                {capability ? `From: ${capability.capability_id}` : "Task-specific"}
              </span>
            </div>
          )}

          {/* Subtasks Section */}
          {isLoadingSubtasks ? (
            <div className="flex items-center justify-center py-4">
              <Loader2 className="w-5 h-5 animate-spin text-slate-500" />
            </div>
          ) : subtasks.length > 0 ? (
            <SubtasksSection
              projectId={projectId}
              taskId={task.id}
              subtasks={subtasks}
              onTogglePass={async (subtaskId, passes) => {
                // Update local state optimistically
                setSubtasks((prev) =>
                  prev.map((s) => s.subtask_id === subtaskId ? { ...s, passes } : s)
                );
                // Would call API here
              }}
            />
          ) : null}

          {/* Labels */}
          {task.labels && task.labels.length > 0 && (
            <div>
              <h3 className="text-sm font-medium text-slate-400 mb-2">Labels</h3>
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

          {/* Checkpoint (if available) */}
          {checkpoint && (
            <CheckpointViewer
              checkpoint={checkpoint}
              onResume={(prompt) => {
                // Could navigate to a resume page or open a dialog
                console.log("Resume prompt copied:", prompt.substring(0, 100) + "...");
              }}
            />
          )}

          {/* Metadata */}
          <div className="text-xs text-slate-500 space-y-1 pt-4 border-t border-slate-800">
            <p>Status: <span className="text-slate-300">{task.status}</span></p>
            {task.created_at && (
              <p>Created: {new Date(task.created_at).toLocaleDateString()}</p>
            )}
            {task.started_at && (
              <p>Started: {new Date(task.started_at).toLocaleDateString()}</p>
            )}
            {task.completed_at && (
              <p>Completed: {new Date(task.completed_at).toLocaleDateString()}</p>
            )}
          </div>
        </SheetBody>
      </SheetContent>
    </Sheet>
  );
}
